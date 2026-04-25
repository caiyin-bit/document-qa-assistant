"""Sole tool registered in V1. Spec §5."""
from uuid import UUID

TOOL_SCHEMA = {
    "name": "search_documents",
    "description": (
        "在用户当前会话已上传的 PDF 中检索相关段落。"
        "回答任何关于文档内容的问题前必须先调用此工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "中文检索 query，可以是用户原问题或提取的关键词",
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
    """Spec §5 + §7 Citation DTO."""

    def __init__(self, *, mem, embedder, min_similarity: float, top_k: int):
        self.mem = mem
        self.embedder = embedder
        self.min_similarity = min_similarity
        self.top_k = top_k

    async def execute(self, *, session_id: UUID, query: str) -> dict:
        emb = self.embedder.encode_one(query)
        hits = await self.mem.search_chunks(
            session_id, query_embedding=list(emb),
            top_k=self.top_k, min_similarity=self.min_similarity,
        )
        if not hits:
            return {"ok": True, "found": False, "chunks": []}

        # de-dupe consecutive same-doc-same-page
        deduped = []
        seen = set()
        for h in hits:
            key = (h["doc_id"], h["page_no"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)

        chunks = [
            {
                "doc_id": h["doc_id"],
                "filename": h["filename"],
                "page_no": h["page_no"],
                "content": h["content"],
                "snippet": _to_snippet(h["content"]),
                "score": h["score"],
            }
            for h in deduped
        ]
        return {"ok": True, "found": True, "chunks": chunks}
