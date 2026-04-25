"""DELETE /sessions/{id} — race-safety and cascade behavior."""
import os
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa",
)

from src.main import make_app_default, _production_deps
from src.models.schemas import DocumentStatus


@pytest.fixture(autouse=True)
def reset_lru_caches():
    import src.db.session as _ses
    _production_deps.cache_clear()
    _ses._default_sm = None
    yield
    _production_deps.cache_clear()
    _ses._default_sm = None


@pytest_asyncio.fixture
async def client(db_session):
    app = make_app_default()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_delete_session_with_processing_doc_returns_409(client, db_session):
    """A session with any doc in 'processing' state must not be deletable —
    cascading the delete would remove the documents row out from under the
    in-flight ingestion task and crash it on FK violation when it tries to
    insert the next chunk batch."""
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    # default status is processing
    await mem.create_document(
        user_id=user.id, session_id=sess.id,
        filename="x.pdf", page_count=10, byte_size=1024,
    )

    r = await client.delete(f"/sessions/{sess.id}")
    assert r.status_code == 409
    assert "解析中" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_session_with_only_ready_docs_succeeds(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(
        user_id=user.id, session_id=sess.id,
        filename="x.pdf", page_count=1, byte_size=1,
    )
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    r = await client.delete(f"/sessions/{sess.id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_session_with_failed_docs_succeeds(client, db_session):
    """Failed-state docs are not racing with anyone — the ingestion task that
    produced them already exited. Allow delete."""
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(
        user_id=user.id, session_id=sess.id,
        filename="x.pdf", page_count=1, byte_size=1,
    )
    await mem.update_document(
        doc.id, status=DocumentStatus.failed, error_message="some error",
    )

    r = await client.delete(f"/sessions/{sess.id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_empty_session_succeeds(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)

    r = await client.delete(f"/sessions/{sess.id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_unknown_session_returns_404(client, db_session):
    r = await client.delete(
        "/sessions/00000000-0000-0000-0000-000000000099"
    )
    assert r.status_code == 404
