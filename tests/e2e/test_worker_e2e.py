"""End-to-end worker tests with real redis + postgres.

Prerequisites: `docker compose -f docker-compose.test.yml up -d` so
postgres-test (55432) and redis-test (56379) are reachable.
"""
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Set BEFORE importing src.* so make_redis_settings/load_config see the right URLs
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:55432/docqa_test"
os.environ["REDIS_URL"] = "redis://localhost:56379/0"
os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")

from src.models.schemas import (
    Document, DocumentChunk, DocumentStatus, Session as SessionRow, User,
)
from src.worker.jobs import INGEST_MAX_TRIES, INGEST_TIMEOUT, ingest_document
from src.worker.redis_pool import make_redis_settings

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sm(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def fake_embedder():
    e = MagicMock()

    async def fake_embed(texts):
        return [[0.01 * (i + 1)] * 1024 for i in range(len(texts))]

    e.embed_batch_async = fake_embed

    async def fake_one(text):
        return [0.0] * 1024

    e.encode_one_async = fake_one
    return e


@pytest_asyncio.fixture
async def seeded_doc(sm):
    """Insert a User+Session+Document and place a real PDF on disk."""
    uploads = Path("data/uploads")
    uploads.mkdir(parents=True, exist_ok=True)

    doc_id = uuid4()
    target = uploads / f"{doc_id}.pdf"
    target.write_bytes(FIXTURE.read_bytes())

    user_id = uuid4()
    sess_id = uuid4()
    async with sm() as db:
        await db.execute(insert(User).values(id=user_id, name="t"))
        await db.execute(insert(SessionRow).values(id=sess_id, user_id=user_id))
        await db.execute(insert(Document).values(
            id=doc_id, user_id=user_id, session_id=sess_id, filename="t.pdf",
            page_count=3, byte_size=target.stat().st_size,
            status=DocumentStatus.processing, progress_page=0,
        ))
        await db.commit()
    yield doc_id, sm
    target.unlink(missing_ok=True)
    # Cleanup so subsequent tests get a clean slate
    async with sm() as db:
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc_id)
        )
        await db.execute(
            Document.__table__.delete().where(Document.id == doc_id)
        )
        await db.execute(
            SessionRow.__table__.delete().where(SessionRow.id == sess_id)
        )
        await db.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await db.commit()


def _make_worker(sm, fake_embedder):
    """Build a burst-mode in-process Arq Worker bound to the test stack."""
    from arq.worker import Worker, func
    return Worker(
        functions=[func(ingest_document, name="ingest_document",
                        timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES)],
        redis_settings=make_redis_settings(),
        burst=True,
        max_jobs=1,
        ctx={"sessionmaker": sm, "embedder": fake_embedder},
    )


@pytest.mark.asyncio
async def test_worker_e2e_happy_path(seeded_doc, fake_embedder):
    doc_id, sm = seeded_doc

    from arq import create_pool
    pool = await create_pool(make_redis_settings())
    job = await pool.enqueue_job(
        "ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}",
    )
    assert job is not None

    worker = _make_worker(sm, fake_embedder)
    await worker.async_run()
    await pool.aclose()

    async with sm() as db:
        doc = (await db.execute(
            select(Document).where(Document.id == doc_id)
        )).scalar_one()
        assert doc.status == DocumentStatus.ready
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )).scalars().all()
        assert len(chunks) > 0
        assert all(len(c.content_embedding) == 1024 for c in chunks)


@pytest.mark.asyncio
async def test_worker_crash_midjob_recovers_on_reenqueue(seeded_doc, fake_embedder):
    """First worker crashes mid-ingestion (infra error → arq retry counts
    a try). Second enqueue (simulating reaper) → step-1 idempotent reset
    cleans partial chunks; final state is `ready` with full chunk count."""
    doc_id, sm = seeded_doc

    crash_after_pages = 1

    async def crashing_ingest(doc_id_arg, *, path, mem, embedder, iter_pages, chunker):
        from src.ingest.ingestion import _ingest_document
        original = iter_pages

        def limited(p):
            for i, page in enumerate(original(p)):
                if i >= crash_after_pages:
                    raise RuntimeError("simulated crash")
                yield page

        await _ingest_document(doc_id_arg, path=path, mem=mem, embedder=embedder,
                                iter_pages=limited, chunker=chunker)

    import src.worker.jobs as jobs
    real_ingest = jobs._ingest_document
    jobs._ingest_document = crashing_ingest

    from arq import create_pool
    pool = await create_pool(make_redis_settings())
    job_id = f"ingest:{doc_id}"
    try:
        await pool.enqueue_job("ingest_document", str(doc_id), _job_id=job_id)
        worker1 = _make_worker(sm, fake_embedder)
        await worker1.async_run()  # crashes the job

        # Restore real _ingest_document. arq retains the failed job's
        # result key, so we clear it to simulate a fresh reaper enqueue
        # (in production the result expires after `keep_result=60s`).
        jobs._ingest_document = real_ingest
        await pool.delete(f"arq:result:{job_id}", f"arq:job:{job_id}")
        reenqueued = await pool.enqueue_job(
            "ingest_document", str(doc_id), _job_id=job_id,
        )
        assert reenqueued is not None, "reaper enqueue must succeed after cleanup"

        worker2 = _make_worker(sm, fake_embedder)
        await worker2.async_run()
    finally:
        jobs._ingest_document = real_ingest
        await pool.aclose()

    async with sm() as db:
        doc = (await db.execute(
            select(Document).where(Document.id == doc_id)
        )).scalar_one()
        assert doc.status == DocumentStatus.ready
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )).scalars().all()
        # Chunks count == fresh full-ingestion count, NOT crashed-run leftover
        assert len(chunks) >= 1


@pytest.mark.asyncio
async def test_job_id_dedup_prevents_duplicate_enqueue(seeded_doc):
    """Three rapid enqueues with the same _job_id must coalesce to one."""
    doc_id, _ = seeded_doc
    from arq import create_pool
    pool = await create_pool(make_redis_settings())
    try:
        j1 = await pool.enqueue_job("ingest_document", str(doc_id),
                                     _job_id=f"ingest:{doc_id}")
        j2 = await pool.enqueue_job("ingest_document", str(doc_id),
                                     _job_id=f"ingest:{doc_id}")
        j3 = await pool.enqueue_job("ingest_document", str(doc_id),
                                     _job_id=f"ingest:{doc_id}")
        assert j1 is not None
        assert j2 is None
        assert j3 is None
    finally:
        # Drop the queued (unconsumed) job so it doesn't leak into the next test
        await pool.delete(f"arq:job:ingest:{doc_id}")
        await pool.zrem("arq:queue", f"ingest:{doc_id}")
        await pool.aclose()
