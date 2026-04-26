import os
import pytest
import pytest_asyncio

os.environ.setdefault("GEMINI_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")

from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA, _to_snippet
from src.models.schemas import DocumentStatus


def test_schema_has_query_param():
    assert TOOL_SCHEMA["name"] == "search_documents"
    assert "query" in TOOL_SCHEMA["parameters"]["properties"]


@pytest.mark.asyncio
async def test_rerank_reorders_and_truncates_to_top_n():
    """Reranker should reorder hits by its own score (not vector cosine)
    and truncate to top_n. Test uses a fake reranker that returns scores
    inverted from the vector score — so #1 by vector becomes last by rerank."""
    from unittest.mock import AsyncMock
    from uuid import UUID
    from src.tools.search_documents import SearchDocumentsTool

    fake_mem = AsyncMock()
    # 4 hits ordered by descending RRF score (post-fusion)
    fake_mem.search_chunks_hybrid = AsyncMock(return_value=[
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 1,
         "content": "vector-best", "score": 0.9},
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 2,
         "content": "vector-2nd", "score": 0.8},
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 3,
         "content": "vector-3rd", "score": 0.7},
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 4,
         "content": "vector-4th", "score": 0.6},
    ])

    fake_embedder = AsyncMock()
    fake_embedder.encode_one_async = AsyncMock(return_value=[0.0] * 1024)

    class _RerankerInverts:
        async def score_pairs_async(self, q, passages):
            # Inverted ordering: longer passage index = higher rerank score.
            return [float(i) for i in range(len(passages))]

    tool = SearchDocumentsTool(
        mem=fake_mem, embedder=fake_embedder,
        min_similarity=0.0, top_k=10,
        reranker=_RerankerInverts(), rerank_top_n=2,
    )
    out = await tool.execute(session_id=UUID(int=1), query="x")
    assert out["found"] is True
    assert len(out["chunks"]) == 2  # truncated to top_n
    # vector ranked d1/p1 first; reranker inverted → p4 first now.
    assert out["chunks"][0]["page_no"] == 4
    assert out["chunks"][1]["page_no"] == 3
    # score replaced with rerank score
    assert out["chunks"][0]["score"] == 3.0


@pytest.mark.asyncio
async def test_uses_hybrid_when_memory_supports_it():
    """If MemoryService exposes search_chunks_hybrid, the tool must call
    that (not search_chunks). Verifies we wired the new RRF path through."""
    from unittest.mock import AsyncMock
    from uuid import UUID
    from src.tools.search_documents import SearchDocumentsTool

    fake_mem = AsyncMock()
    fake_mem.search_chunks_hybrid = AsyncMock(return_value=[
        {"chunk_id": "c1", "doc_id": "d1", "filename": "x.pdf",
         "page_no": 1, "content": "via hybrid", "score": 0.99},
    ])
    # search_chunks would be called by the fallback; assert it's NOT.
    fake_mem.search_chunks = AsyncMock(side_effect=AssertionError(
        "must not be called when search_chunks_hybrid is available"))

    fake_embedder = AsyncMock()
    fake_embedder.encode_one_async = AsyncMock(return_value=[0.0] * 1024)

    tool = SearchDocumentsTool(
        mem=fake_mem, embedder=fake_embedder,
        min_similarity=0.0, top_k=10, reranker=None,
    )
    out = await tool.execute(session_id=UUID(int=1), query="x")
    assert out["found"] is True
    fake_mem.search_chunks_hybrid.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_reranker_keeps_vector_order():
    """When reranker is None, output must preserve vector cosine ordering
    (back-compat for tests/setups without the reranker model)."""
    from unittest.mock import AsyncMock
    from uuid import UUID
    from src.tools.search_documents import SearchDocumentsTool

    fake_mem = AsyncMock()
    fake_mem.search_chunks_hybrid = AsyncMock(return_value=[
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 1,
         "content": "best", "score": 0.9},
        {"doc_id": "d1", "filename": "x.pdf", "page_no": 2,
         "content": "second", "score": 0.7},
    ])
    fake_embedder = AsyncMock()
    fake_embedder.encode_one_async = AsyncMock(return_value=[0.0] * 1024)

    tool = SearchDocumentsTool(
        mem=fake_mem, embedder=fake_embedder,
        min_similarity=0.0, top_k=10,
        reranker=None,
    )
    out = await tool.execute(session_id=UUID(int=1), query="x")
    assert [c["page_no"] for c in out["chunks"]] == [1, 2]
    assert out["chunks"][0]["score"] == 0.9


def test_registry_emits_openai_function_envelope():
    """Strict OpenAI-compatible gateways require each tool to be wrapped as
    {type:'function', function:{name, description, parameters}}. Missing
    the wrapper returns 400 'Field required'."""
    from src.core.tool_registry import ToolRegistry
    registry = ToolRegistry(
        mem=None, embedder=None, min_similarity=0.0, top_k=1,
    )
    schemas = registry.schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "search_documents"
    assert "parameters" in s["function"]


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

    # `min_similarity` only gates the vector recall path; the hybrid
    # keyword path (pg_trgm) still surfaces chunks if any character
    # n-grams overlap. With a query that shares no characters with the
    # only chunk, both paths yield zero → found stays false.
    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.99, top_k=8)
    out = await tool.execute(session_id=sess.id, query="abcdefghijk")
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
        # snippet only — full content is no longer returned to keep LLM
        # input context small.
        assert str(s2.id) not in c["snippet"]
