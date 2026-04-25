import pytest
from uuid import uuid4
from src.core.memory_service import MemoryService
from src.models.schemas import DocumentStatus

@pytest.fixture
async def mem(db_session):
    return MemoryService(db_session)

@pytest.fixture
async def user(mem):
    return await mem.upsert_demo_user()

@pytest.fixture
async def session_obj(mem, user):
    return await mem.create_session(user.id)

@pytest.mark.asyncio
async def test_create_session_and_list(mem, user):
    s1 = await mem.create_session(user.id)
    s2 = await mem.create_session(user.id)
    rows = await mem.list_sessions(user.id, limit=10)
    assert {r.id for r in rows} == {s1.id, s2.id}

@pytest.mark.asyncio
async def test_create_document_returns_full_meta(mem, user, session_obj):
    doc = await mem.create_document(
        user_id=user.id, session_id=session_obj.id,
        filename="test.pdf", page_count=10, byte_size=12345,
    )
    assert doc.status == DocumentStatus.processing
    assert doc.page_count == 10
    assert doc.progress_page == 0

@pytest.mark.asyncio
async def test_update_document_progress_and_status(mem, user, session_obj):
    doc = await mem.create_document(
        user_id=user.id, session_id=session_obj.id,
        filename="x.pdf", page_count=5, byte_size=100,
    )
    await mem.update_document(doc.id, progress_page=3)
    refreshed = await mem.get_document(doc.id)
    assert refreshed.progress_page == 3
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    refreshed = await mem.get_document(doc.id)
    assert refreshed.status == DocumentStatus.ready

@pytest.mark.asyncio
async def test_list_documents_for_session(mem, user, session_obj):
    s2 = await mem.create_session(user.id)
    d1 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="a.pdf", page_count=1, byte_size=1)
    d2 = await mem.create_document(user_id=user.id, session_id=s2.id,
                                    filename="b.pdf", page_count=1, byte_size=1)
    rows = await mem.list_documents(session_obj.id)
    assert {r.id for r in rows} == {d1.id}

@pytest.mark.asyncio
async def test_count_documents_by_status(mem, user, session_obj):
    d1 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="a.pdf", page_count=1, byte_size=1)
    d2 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="b.pdf", page_count=1, byte_size=1)
    await mem.update_document(d1.id, status=DocumentStatus.ready)
    counts = await mem.count_documents_by_status(session_obj.id)
    assert counts == {"processing": 1, "ready": 1, "failed": 0}

@pytest.mark.asyncio
async def test_bulk_insert_chunks_and_search(mem, user, session_obj):
    doc = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                     filename="a.pdf", page_count=2, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "腾讯营收 6605 亿元",
         "embedding": [0.1] * 1024, "token_count": 10},
        {"page_no": 2, "chunk_idx": 1, "content": "阿里营收 9000 亿元",
         "embedding": [0.2] * 1024, "token_count": 10},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    hits = await mem.search_chunks(session_obj.id, query_embedding=[0.1] * 1024,
                                    top_k=10, min_similarity=0.0)
    assert len(hits) == 2

@pytest.mark.asyncio
async def test_delete_document_cascades_chunks_but_keeps_message_citations(
    mem, user, session_obj
):
    doc = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                     filename="a.pdf", page_count=1, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "x",
         "embedding": [0.0] * 1024, "token_count": 1},
    ])
    citations = [{"doc_id": str(doc.id), "filename": "a.pdf",
                  "page_no": 1, "snippet": "x", "score": 0.9}]
    await mem.save_assistant_message(session_obj.id, "answer", citations=citations)

    await mem.delete_document(doc.id)

    assert await mem.get_document(doc.id) is None
    msgs = await mem.list_messages(session_obj.id)
    assert msgs[-1].citations == citations
