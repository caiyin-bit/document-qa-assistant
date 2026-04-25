import pytest
from src.ingest.ingestion import cleanup_stale_documents
from src.models.schemas import DocumentStatus


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
