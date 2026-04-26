"""Tool registry — V1 has only search_documents."""
from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA


class ToolRegistry:
    def __init__(
        self, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
    ):
        self._tools = {
            "search_documents": SearchDocumentsTool(
                mem=mem, embedder=embedder,
                min_similarity=min_similarity, top_k=top_k,
                reranker=reranker, rerank_top_n=rerank_top_n,
            ),
        }

    def schemas(self) -> list[dict]:
        # OpenAI Tools API requires each tool wrapped as {type, function}.
        # Some strict gateways (we hit this on a previous SiliconFlow
        # deployment) return 400 "Field required" if the wrapper is
        # missing — keep the wrapper unconditionally for portability.
        return [{"type": "function", "function": TOOL_SCHEMA}]

    async def execute(self, name: str, arguments: dict, *, session_id) -> dict:
        if name not in self._tools:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            return await self._tools[name].execute(session_id=session_id, **arguments)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
