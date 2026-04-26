import os
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")

from src.main import make_app_default, _production_deps
from src.models.schemas import DocumentStatus

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


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
async def test_delete_processing_returns_409(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    # status defaults to processing

    r = await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")
    assert r.status_code == 409
    assert "解析中" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_ready_succeeds_and_cascades(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "x",
         "embedding": [0.0]*1024, "token_count": 1},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    r = await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")
    assert r.status_code == 204

    # The HTTP call used a separate session; bypass the identity map cache by
    # issuing a fresh SELECT instead of db.get().
    from sqlalchemy import select as sa_select, text as sa_text
    from src.models.schemas import Document as DocumentModel, DocumentChunk
    result = await db_session.execute(
        sa_select(DocumentModel).where(DocumentModel.id == doc.id)
    )
    assert result.scalar_one_or_none() is None
    hits = await mem.search_chunks(sess.id, query_embedding=[0.0]*1024,
                                    top_k=10, min_similarity=0.0)
    assert hits == []


@pytest.mark.asyncio
async def test_delete_unknown_returns_404(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    r = await client.delete(
        f"/sessions/{sess.id}/documents/00000000-0000-0000-0000-000000000099"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_preserves_message_citations(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    citations = [{"doc_id": str(doc.id), "filename": "x.pdf",
                  "page_no": 1, "snippet": "hello", "score": 0.9}]
    await mem.save_assistant_message(sess.id, "answer", citations=citations)

    await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")

    msgs = await mem.list_messages(sess.id)
    assert msgs[-1].citations == citations
