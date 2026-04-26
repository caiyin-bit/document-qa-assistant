import os
import pytest
import pytest_asyncio

os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")

from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA, _to_snippet
from src.models.schemas import DocumentStatus


def test_schema_has_query_param():
    assert TOOL_SCHEMA["name"] == "search_documents"
    assert "query" in TOOL_SCHEMA["parameters"]["properties"]


def test_to_snippet_short_content_passthrough():
    assert _to_snippet("短文本") == "短文本"


def test_to_snippet_truncates_with_ellipsis():
    long = "x" * 600
    out = _to_snippet(long, max_chars=480)
    assert len(out) <= 481  # 480 chars + "…"
    assert out.endswith("…")


@pytest.mark.asyncio
async def test_returns_found_true_when_chunks_above_threshold(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="rep.pdf", page_count=1, byte_size=1)
    embedder = BgeEmbedder()
    text = "腾讯 2025 年总营业收入为 6,605 亿元"
    emb = await embedder.encode_one_async(text)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 12, "chunk_idx": 0, "content": text,
         "embedding": list(emb), "token_count": 20},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.0, top_k=8)
    out = await tool.execute(session_id=sess.id, query="腾讯 2025 年总营收")
    assert out["ok"] is True and out["found"] is True
    assert out["chunks"][0]["page_no"] == 12
    assert "snippet" in out["chunks"][0]


@pytest.mark.asyncio
async def test_returns_found_false_when_all_below_threshold(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="rep.pdf", page_count=1, byte_size=1)
    embedder = BgeEmbedder()
    emb = await embedder.encode_one_async("腾讯财报内容")
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "腾讯财报内容",
         "embedding": list(emb), "token_count": 10},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    # Very high threshold → guaranteed empty
    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.99, top_k=8)
    out = await tool.execute(session_id=sess.id, query="完全无关的话题")
    assert out["ok"] is True and out["found"] is False
    assert out["chunks"] == []


@pytest.mark.asyncio
async def test_isolation_between_sessions(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    s1 = await mem.create_session(user.id)
    s2 = await mem.create_session(user.id)
    embedder = BgeEmbedder()

    for sess in [s1, s2]:
        doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                         filename="x.pdf", page_count=1, byte_size=1)
        emb = await embedder.encode_one_async(f"内容 {sess.id}")
        await mem.bulk_insert_chunks(doc.id, [
            {"page_no": 1, "chunk_idx": 0, "content": f"内容 {sess.id}",
             "embedding": list(emb), "token_count": 5},
        ])
        await mem.update_document(doc.id, status=DocumentStatus.ready)

    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.0, top_k=10)
    out = await tool.execute(session_id=s1.id, query="内容")
    for c in out["chunks"]:
        assert str(s2.id) not in c["content"]
