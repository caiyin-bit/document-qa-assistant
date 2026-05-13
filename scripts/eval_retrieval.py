"""Retrieval evaluation harness.

Loads tests/fixtures/retrieval_eval.yaml, ingests the fixture chunks into
a disposable session under a stable eval user, runs the query set under
three retrieval modes (vector / trigram / hybrid), and prints
R@1 / R@3 / R@5 / MRR per mode. Optionally writes the metrics to a JSON
baseline file for comparison across retrieval changes.

Requires:
  - DATABASE_URL env var pointing at a Postgres with pgvector + pg_trgm
    and the project migrations applied.
  - The BGE model accessible via sentence-transformers (downloads on
    first run if not cached).

Usage:
  python scripts/eval_retrieval.py
  python scripts/eval_retrieval.py --modes vector hybrid
  python scripts/eval_retrieval.py --json eval/baseline_2026-05-13.json
  python scripts/eval_retrieval.py --top-k 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.memory_service import MemoryService
from src.db.session import get_engine
from src.embedding.bge_embedder import BgeEmbedder
from src.models.schemas import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Session as DBSession,
    SessionDocument,
    User,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "retrieval_eval.yaml"
)
EVAL_USER_NAME = "eval-bot"
EVAL_USER_EMAIL = "eval-bot@local"


async def _ensure_eval_user(db: AsyncSession) -> User:
    """Create-or-fetch a stable eval user. Reused across runs."""
    res = await db.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid4(),
            name=EVAL_USER_NAME,
            email=EVAL_USER_EMAIL,
            password_hash="!eval-bot!",
        )
        db.add(user)
        await db.flush()
    return user


async def _wipe_eval_data(db: AsyncSession, user_id: UUID) -> None:
    """Remove prior eval sessions/documents so reruns start clean.

    FK order: session_documents → documents (chunks cascade via FK) → sessions.
    """
    sids_result = await db.execute(
        select(DBSession.id).where(DBSession.user_id == user_id)
    )
    sids = sids_result.scalars().all()
    if not sids:
        return
    await db.execute(
        delete(SessionDocument).where(SessionDocument.session_id.in_(sids))
    )
    await db.execute(delete(Document).where(Document.session_id.in_(sids)))
    await db.execute(delete(DBSession).where(DBSession.id.in_(sids)))


async def _load_fixture(
    db: AsyncSession, embedder: BgeEmbedder, user_id: UUID, fixture: dict,
) -> tuple[UUID, dict[str, str]]:
    """Insert fixture documents + chunks. Returns (session_id, chunk_key→chunk_id)."""
    sess = DBSession(id=uuid4(), user_id=user_id)
    db.add(sess)
    await db.flush()

    chunk_key_to_id: dict[str, str] = {}
    for doc_spec in fixture["documents"]:
        doc = Document(
            id=uuid4(),
            user_id=user_id,
            session_id=sess.id,
            filename=doc_spec["filename"],
            page_count=doc_spec["page_count"],
            byte_size=0,
            status=DocumentStatus.ready,
        )
        db.add(doc)
        db.add(SessionDocument(session_id=sess.id, document_id=doc.id))
        await db.flush()

        for idx, c in enumerate(doc_spec["chunks"]):
            emb = await embedder.encode_one_async(c["content"])
            chunk = DocumentChunk(
                id=uuid4(),
                document_id=doc.id,
                page_no=c["page_no"],
                chunk_idx=idx,
                content=c["content"],
                content_embedding=emb,
                token_count=len(c["content"]),
            )
            db.add(chunk)
            await db.flush()
            chunk_key_to_id[c["chunk_key"]] = str(chunk.id)

    await db.commit()
    return sess.id, chunk_key_to_id


async def _run_one_query(
    mem: MemoryService,
    embedder: BgeEmbedder,
    session_id: UUID,
    q: dict,
    mode: str,
    top_k: int,
) -> list[str]:
    """Return ranked chunk_id list for one query under one mode."""
    if mode == "vector":
        qvec = await embedder.encode_one_async(q["query"])
        hits = await mem.search_chunks(
            session_id, query_embedding=qvec, top_k=top_k, min_similarity=0.0,
        )
    elif mode == "trigram":
        hits = await mem.search_chunks_keyword(
            session_id, query=q["query"], top_k=top_k,
        )
    elif mode == "hybrid":
        qvec = await embedder.encode_one_async(q["query"])
        hits = await mem.search_chunks_hybrid(
            session_id,
            query=q["query"],
            query_embedding=qvec,
            top_k=top_k,
            min_similarity=0.0,
        )
    else:
        raise ValueError(f"unknown mode: {mode}")
    return [h["chunk_id"] for h in hits]


def _recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    if not expected:
        return 0.0
    return len(set(ranked[:k]) & expected) / len(expected)


def _mrr(ranked: list[str], expected: set[str]) -> float:
    for i, cid in enumerate(ranked, start=1):
        if cid in expected:
            return 1.0 / i
    return 0.0


async def main_async(args: argparse.Namespace) -> int:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        fixture = yaml.safe_load(f)

    sm = async_sessionmaker(get_engine(), expire_on_commit=False)
    embedder = BgeEmbedder()

    try:
        # Pass 1: ensure user + wipe stale eval data
        async with sm() as db:
            user = await _ensure_eval_user(db)
            await _wipe_eval_data(db, user.id)
            await db.commit()
            user_id = user.id

        # Pass 2: ingest fixture chunks with live embeddings
        async with sm() as db:
            session_id, chunk_key_to_id = await _load_fixture(
                db, embedder, user_id, fixture,
            )

        # Pass 3: run queries across modes
        metrics: dict[str, dict] = {}
        async with sm() as db:
            mem = MemoryService(db)
            for mode in args.modes:
                per_query = []
                for q in fixture["queries"]:
                    expected_ids = {
                        chunk_key_to_id[k] for k in q["expected_chunk_keys"]
                    }
                    ranked = await _run_one_query(
                        mem, embedder, session_id, q, mode, args.top_k,
                    )
                    per_query.append({
                        "id": q["id"],
                        "r@1": _recall_at_k(ranked, expected_ids, 1),
                        "r@3": _recall_at_k(ranked, expected_ids, 3),
                        "r@5": _recall_at_k(ranked, expected_ids, 5),
                        "mrr": _mrr(ranked, expected_ids),
                    })
                metrics[mode] = {
                    "per_query": per_query,
                    "avg_r@1": statistics.mean(p["r@1"] for p in per_query),
                    "avg_r@3": statistics.mean(p["r@3"] for p in per_query),
                    "avg_r@5": statistics.mean(p["r@5"] for p in per_query),
                    "avg_mrr": statistics.mean(p["mrr"] for p in per_query),
                }
    finally:
        embedder.close()

    print(f"{'mode':<10} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6}")
    print("-" * 40)
    for mode, m in metrics.items():
        print(
            f"{mode:<10} {m['avg_r@1']:>6.3f} {m['avg_r@3']:>6.3f} "
            f"{m['avg_r@5']:>6.3f} {m['avg_mrr']:>6.3f}"
        )

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "top_k": args.top_k,
                    "fixture": str(FIXTURE_PATH.name),
                    "metrics": metrics,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nbaseline written to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run retrieval evaluation (vector / trigram / hybrid) against the "
            "tests/fixtures/retrieval_eval.yaml fixture and print R@k / MRR. "
            "Requires DATABASE_URL pointing at a Postgres with the project "
            "migrations applied."
        ),
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["vector", "trigram", "hybrid"],
        choices=["vector", "trigram", "hybrid"],
        help="retrieval modes to evaluate (default: all three)",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="top-K cutoff for retrieval and R@k computation (default: 5)",
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="write JSON baseline to this path",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
