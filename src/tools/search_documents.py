"""Sole tool registered in V1. Spec §5."""
import logging
from uuid import UUID

from src.ingest.zh_normalize import to_simplified

log = logging.getLogger(__name__)

TOOL_SCHEMA = {
    "name": "search_documents",
    "description": (
        "在用户当前会话已上传的 PDF 中检索相关段落。"
        "回答任何关于文档内容的问题前必须先调用此工具。"
        "采用混合检索（向量 + 关键字）+ 重排，每次返回最相关的 5 段。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "广覆盖中文检索 query。把用户问题的核心概念展开成"
                    "2-4 个同义词，用空格拼成一个 query。"
                    "**关键约束**：只展开核心概念，**不要**加\"报告期末\""
                    "\"截至年底\"\"十二月三十一日\"这类财报通用模板词——"
                    "它们出现在所有附注页，会稀释真正的命中。"
                    "例如用户问\"期末员工总数\"，应当传："
                    "\"员工总数 雇员人数 员工数量 集团雇员\"。"
                    "财报核心同义：员工↔雇员；营收↔总收入；净利润↔归母净利润。"
                ),
            }
        },
        "required": ["query"],
    },
}


def _to_snippet(content: str, max_chars: int = 480) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "…"


class SearchDocumentsTool:
    """Spec §5 + §7 Citation DTO.

    Pipeline: BGE encode query → pgvector cosine top_k → page-dedup →
    optional cross-encoder rerank → top_n snippets out.

    Why rerank: bi-encoder cosine (BGE) is fast but coarse; the cross-
    encoder reads (query, passage) jointly and is much more accurate at
    "does this passage actually answer the question". Running it on the
    top-k shortlist (~16 docs) is the standard recall→precision pattern.
    Disable via `reranker=None` to fall back to vector-only ordering.
    """

    def __init__(
        self, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
    ):
        self.mem = mem
        self.embedder = embedder
        self.min_similarity = min_similarity
        self.top_k = top_k
        self.reranker = reranker
        self.rerank_top_n = rerank_top_n

    async def execute(self, *, session_id: UUID, query: str) -> dict:
        # Normalise query to simplified Chinese so it matches the indexed
        # form (ingestion also normalises). Without this, simp queries miss
        # all trad-Chinese chunks on the keyword path.
        original_query = query
        query = to_simplified(query)
        log.info("search.query original=%r normalized=%r", original_query, query)
        emb = await self.embedder.encode_one_async(query)
        # Hybrid recall: vector cosine + pg_trgm keyword, fused via RRF.
        # Falls back to plain vector when memory_service doesn't expose
        # the hybrid method (older test mocks).
        if hasattr(self.mem, "search_chunks_hybrid"):
            hits = await self.mem.search_chunks_hybrid(
                session_id, query=query, query_embedding=list(emb),
                top_k=self.top_k, min_similarity=self.min_similarity,
            )
        else:
            hits = await self.mem.search_chunks(
                session_id, query_embedding=list(emb),
                top_k=self.top_k, min_similarity=self.min_similarity,
            )
        if not hits:
            return {"ok": True, "found": False, "chunks": []}

        # de-dupe consecutive same-doc-same-page (after vector-similarity
        # ordering, so we keep the highest-scoring chunk per page).
        deduped = []
        seen = set()
        for h in hits:
            key = (h["doc_id"], h["page_no"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)

        # Cross-encoder rerank: re-score the shortlist with a model that
        # reads (query, passage) jointly. Replace the bi-encoder cosine
        # `score` with the rerank score so downstream sort is consistent.
        if self.reranker is not None and len(deduped) > 1:
            passages = [_to_snippet(h["content"]) for h in deduped]
            rerank_scores = await self.reranker.score_pairs_async(query, passages)
            for h, s in zip(deduped, rerank_scores):
                h["score"] = float(s)
            deduped.sort(key=lambda h: h["score"], reverse=True)
            deduped = deduped[: self.rerank_top_n]
            log.info("search.rerank_top pages=%s scores=%s",
                     [h["page_no"] for h in deduped],
                     [round(h["score"], 3) for h in deduped])

        # Only `snippet` (480-char excerpt) is sent back; the full chunk text
        # is not — it inflates the next LLM call's input context dramatically
        # (16 chunks × ~1500 chars = ~24KB) and TTFT goes from ~12s to 2+ min.
        # The snippet is enough for the model to compose an answer; the
        # citation card on the frontend also displays only the snippet.
        chunks = [
            {
                "doc_id": h["doc_id"],
                "filename": h["filename"],
                "page_no": h["page_no"],
                "snippet": _to_snippet(h["content"]),
                "score": h["score"],
            }
            for h in deduped
        ]
        return {"ok": True, "found": True, "chunks": chunks}
