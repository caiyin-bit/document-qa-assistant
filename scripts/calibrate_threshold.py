#!/usr/bin/env python3
"""Threshold calibration. Spec §5/§13 T2.5.

Usage:
  python scripts/calibrate_threshold.py <session_id_with_ready_doc>

Prints per-query top-K similarity scores and a suggested MIN_SIMILARITY value.
DOES NOT modify config. Copy the suggested value to .env if desired.
"""
import asyncio
import os
import sys
from statistics import mean

# Set required env vars before importing app modules
os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")

RELEVANT_QUERIES = ["总营收", "业务板块", "风险因素"]
IRRELEVANT_QUERIES = ["今天天气如何", "梅西踢哪个俱乐部", "如何做红烧肉"]
TOP_K = 8


async def main(session_id: str):
    from src.db.session import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder

    embedder = BgeEmbedder()
    Sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    relevant_min = []
    irrelevant_max = []

    async with Sessionmaker() as db:
        mem = MemoryService(db)
        for label, queries, accumulator in [
            ("RELEVANT", RELEVANT_QUERIES, relevant_min),
            ("IRRELEVANT", IRRELEVANT_QUERIES, irrelevant_max),
        ]:
            print(f"\n=== {label} ===")
            for q in queries:
                emb = embedder.encode_one(q)
                hits = await mem.search_chunks(
                    session_id, query_embedding=list(emb),
                    top_k=TOP_K, min_similarity=0.0,
                )
                scores = [h["score"] for h in hits]
                print(f"  query={q!r:<30} top-{TOP_K} scores={[f'{s:.3f}' for s in scores]}")
                if label == "RELEVANT" and scores:
                    accumulator.append(min(scores[: max(1, TOP_K // 2)]))
                if label == "IRRELEVANT" and scores:
                    accumulator.append(max(scores))

    if relevant_min and irrelevant_max:
        suggested = round((mean(relevant_min) + mean(irrelevant_max)) / 2, 2)
        print(f"\nRelevant lower-bound (avg mid-top): {mean(relevant_min):.3f}")
        print(f"Irrelevant upper-bound (avg max):    {mean(irrelevant_max):.3f}")
        print(f"\nSuggested MIN_SIMILARITY = {suggested}")
        print(f"Add to .env (optional):  MIN_SIMILARITY={suggested}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
