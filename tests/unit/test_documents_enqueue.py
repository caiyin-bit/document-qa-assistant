"""Backend upload endpoint: arq enqueue happy path + Redis failure +
de-dup result classification."""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")

from src.main import _production_deps

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


@pytest.fixture(autouse=True)
def reset_lru_caches():
    import src.db.session as _ses
    _production_deps.cache_clear()
    _ses._default_sm = None
    yield
    _production_deps.cache_clear()
    _ses._default_sm = None


@pytest.fixture
def stub_arq_pool_create(monkeypatch):
    """Prevent the lifespan startup hook from dialing real Redis."""
    fake_pool = MagicMock()
    fake_pool.aclose = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="ingest:xxx"))
    monkeypatch.setattr("src.main.create_pool",
                         AsyncMock(return_value=fake_pool))
    return fake_pool


@pytest_asyncio.fixture
async def client(db_session, stub_arq_pool_create):
    from src.main import make_app_default
    app = make_app_default()
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def session_id(client):
    r = await client.post("/sessions")
    assert r.status_code == 200
    return r.json()["session_id"]


@pytest.mark.asyncio
async def test_upload_calls_enqueue_with_deterministic_job_id(
    client, session_id, stub_arq_pool_create
):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]
    stub_arq_pool_create.enqueue_job.assert_awaited_once()
    args, kwargs = stub_arq_pool_create.enqueue_job.call_args
    assert args[0] == "ingest_document"
    assert args[1] == doc_id
    assert kwargs.get("_job_id") == f"ingest:{doc_id}"


@pytest.mark.asyncio
async def test_upload_handles_redis_failure_returns_503(
    client, session_id, stub_arq_pool_create
):
    from redis.exceptions import RedisError

    captured_doc_ids: list[str] = []

    async def fail_after_capture(*args, **kwargs):
        captured_doc_ids.append(args[1])
        raise RedisError("down")

    stub_arq_pool_create.enqueue_job = AsyncMock(side_effect=fail_after_capture)
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 503, r.text
    assert "队列" in r.json().get("detail", "")
    # The specific upload's file must have been cleaned up
    assert len(captured_doc_ids) == 1
    final = Path(f"data/uploads/{captured_doc_ids[0]}.pdf")
    assert not final.exists()


@pytest.mark.asyncio
async def test_upload_atomic_rename_happens_before_enqueue(
    client, session_id, stub_arq_pool_create
):
    """When enqueue is called, the final PDF must already exist on disk."""
    seen_existence: list[bool] = []

    async def check_then_record(*args, **kwargs):
        doc_id = args[1]
        path = Path(f"data/uploads/{doc_id}.pdf")
        seen_existence.append(path.is_file())
        return MagicMock(job_id=f"ingest:{doc_id}")

    stub_arq_pool_create.enqueue_job = AsyncMock(side_effect=check_then_record)
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200
    assert seen_existence == [True]
