import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.models.schemas import DocumentStatus

os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")


@pytest.fixture
def stub_arq_pool(monkeypatch):
    """Replace `src.main.create_pool` with a stub returning a closeable mock.
    Tests that build the production app on host (no real redis reachable)
    must use this so the lifespan startup hook doesn't dial redis."""
    fake_pool = MagicMock()
    fake_pool.aclose = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="ingest:test"))
    monkeypatch.setattr("src.main.create_pool",
                         AsyncMock(return_value=fake_pool))
    return fake_pool


@pytest.mark.asyncio
async def test_reaper_reenqueues_processing_docs_without_touching_state(db_session):
    """Reaper enqueues with deterministic _job_id; doc state and chunks
    are NOT touched (the worker's step-1 owns cleanup)."""
    from sqlalchemy import insert, select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from uuid import uuid4
    from src.models.schemas import Document, DocumentChunk, User, Session as SessionRow
    from src.api.reaper import reenqueue_processing_documents
    from src.db.session import get_engine

    user_id = uuid4()
    sess_id = uuid4()
    doc_id = uuid4()
    await db_session.execute(insert(User).values(id=user_id, name="t"))
    await db_session.execute(insert(SessionRow).values(id=sess_id, user_id=user_id))
    await db_session.execute(insert(Document).values(
        id=doc_id, user_id=user_id, session_id=sess_id, filename="x.pdf",
        page_count=10, byte_size=1000, status=DocumentStatus.processing,
        progress_page=42,
    ))
    await db_session.execute(insert(DocumentChunk).values(
        id=uuid4(), document_id=doc_id, page_no=1, chunk_idx=0,
        content="leftover", content_embedding=[0.0] * 1024, token_count=8,
    ))
    await db_session.commit()

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=MagicMock())
    sm = async_sessionmaker(get_engine(), expire_on_commit=False)

    await reenqueue_processing_documents(arq_pool=fake_pool, sessionmaker=sm)

    fake_pool.enqueue_job.assert_awaited_once()
    args, kwargs = fake_pool.enqueue_job.call_args
    assert args == ("ingest_document", str(doc_id))
    assert kwargs == {"_job_id": f"ingest:{doc_id}"}

    # Doc state untouched
    await db_session.rollback()  # drop snapshot held by db_session
    row = (await db_session.execute(
        select(Document).where(Document.id == doc_id)
    )).scalar_one()
    assert row.status == DocumentStatus.processing
    assert row.progress_page == 42
    chunks = (await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )).scalars().all()
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_reaper_continues_when_one_enqueue_fails(db_session):
    """A RedisError on one doc must not abort the sweep for the others."""
    from sqlalchemy import insert
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from uuid import uuid4
    from redis.exceptions import RedisError
    from src.models.schemas import Document, User, Session as SessionRow
    from src.api.reaper import reenqueue_processing_documents
    from src.db.session import get_engine

    user_id = uuid4()
    sess_id = uuid4()
    doc_a = uuid4()
    doc_b = uuid4()
    await db_session.execute(insert(User).values(id=user_id, name="t"))
    await db_session.execute(insert(SessionRow).values(id=sess_id, user_id=user_id))
    for did in (doc_a, doc_b):
        await db_session.execute(insert(Document).values(
            id=did, user_id=user_id, session_id=sess_id, filename="x.pdf",
            page_count=1, byte_size=1, status=DocumentStatus.processing,
        ))
    await db_session.commit()

    call_count = {"n": 0}

    async def flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RedisError("transient")
        return MagicMock()

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(side_effect=flaky)
    sm = async_sessionmaker(get_engine(), expire_on_commit=False)

    await reenqueue_processing_documents(arq_pool=fake_pool, sessionmaker=sm)
    assert call_count["n"] == 2  # both attempted


@pytest.mark.asyncio
async def test_lifespan_creates_and_closes_arq_pool(monkeypatch):
    """Backend startup must create an arq Redis pool; shutdown must close it."""
    os.environ.setdefault("GEMINI_API_KEY", "dummy")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    os.environ["REDIS_URL"] = "redis://redis:6379/0"

    from src.main import _production_deps, make_app_default

    _production_deps.cache_clear()

    fake_pool = MagicMock()
    fake_pool.aclose = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="ingest:test"))

    create_calls = []

    async def fake_create_pool(settings, **kw):
        create_calls.append(settings)
        return fake_pool

    monkeypatch.setattr("src.main.create_pool", fake_create_pool)

    app = make_app_default()
    async with app.router.lifespan_context(app):
        assert len(create_calls) == 1
        assert app.state.arq_pool is fake_pool

    fake_pool.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_closes_embedder(stub_arq_pool):
    """FastAPI shutdown event must call embedder.close(wait=False)."""
    os.environ.setdefault("GEMINI_API_KEY", "dummy")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    from src.main import make_app_default, _production_deps

    _production_deps.cache_clear()
    app = make_app_default()
    deps = _production_deps()
    fake_close = MagicMock()
    deps.embedder.close = fake_close

    async with app.router.lifespan_context(app):
        pass  # shutdown fires when block exits

    fake_close.assert_called_once_with(wait=False)
