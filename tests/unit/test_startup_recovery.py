import os
import pytest
from src.ingest.ingestion import cleanup_stale_documents
from src.models.schemas import DocumentStatus

os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")


@pytest.mark.asyncio
async def test_stale_processing_marked_failed_and_chunks_purged(db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=10, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "p1",
         "embedding": [0.0]*1024, "token_count": 1},
    ])
    refreshed = await mem.get_document(doc.id)
    assert refreshed.status == DocumentStatus.processing

    await cleanup_stale_documents(mem)

    after = await mem.get_document(doc.id)
    assert after.status == DocumentStatus.failed
    assert "解析中断" in after.error_message
    hits = await mem.search_chunks(sess.id, query_embedding=[0.0]*1024,
                                    top_k=10, min_similarity=0.0)
    assert hits == []


@pytest.mark.asyncio
async def test_app_startup_invokes_cleanup(db_session):
    """Verify the startup hook actually runs cleanup_stale_documents on app startup."""
    from src.core.memory_service import MemoryService
    from src.main import make_app_default, _production_deps
    import src.db.session as dbs
    from src.db.session import get_engine, make_sessionmaker

    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    # Commit so the startup hook's separate DB session can see the row
    await db_session.commit()

    # Clear caches so a fresh app instance gets its own engine/sessionmaker
    _production_deps.cache_clear()
    dbs._default_sm = None

    app = make_app_default()
    # Directly invoke startup handlers (ASGITransport does not trigger lifespan)
    for handler in app.router.on_startup:
        await handler()

    # The hook committed via its own session. Use a fresh independent session to
    # verify — db_session's open transaction sees the pre-hook snapshot even after
    # rollback due to PostgreSQL read-committed semantics within a connection.
    from sqlalchemy import select
    from src.models.schemas import Document
    sm = make_sessionmaker(get_engine())
    async with sm() as fresh_db:
        result = await fresh_db.execute(select(Document).where(Document.id == doc.id))
        after = result.scalar_one()
    assert after.status == DocumentStatus.failed


@pytest.mark.asyncio
async def test_shutdown_closes_embedder():
    """FastAPI shutdown event must call embedder.close(wait=False)."""
    import os
    os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    from src.main import make_app_default, _production_deps
    from unittest.mock import MagicMock

    _production_deps.cache_clear()
    app = make_app_default()
    deps = _production_deps()
    fake_close = MagicMock()
    deps.embedder.close = fake_close

    async with app.router.lifespan_context(app):
        pass  # shutdown fires when block exits

    fake_close.assert_called_once_with(wait=False)
