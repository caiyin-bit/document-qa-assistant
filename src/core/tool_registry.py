"""Tool registry — V1 has only search_documents."""
from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA


class ToolRegistry:
    def __init__(self, *, mem, embedder, min_similarity: float, top_k: int):
        self._tools = {
            "search_documents": SearchDocumentsTool(
                mem=mem, embedder=embedder,
                min_similarity=min_similarity, top_k=top_k,
            ),
        }

    @classmethod
    def default(cls, *args, **kwargs):
        # Backward-compat shim for chat.py call sites until T13 rewires.
        # Returns an empty registry; real wiring happens in T13.
        return _EmptyRegistry()

    def schemas(self) -> list[dict]:
        return [TOOL_SCHEMA]

    async def execute(self, name: str, arguments: dict, *, session_id) -> dict:
        if name not in self._tools:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            return await self._tools[name].execute(session_id=session_id, **arguments)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}


class _EmptyRegistry:
    """Backward-compat shim until T13 rewires chat.py to call ToolRegistry(...)
    with proper deps. Returns empty schemas and a stub execute."""
    def schemas(self):
        return []
    async def execute(self, *args, **kwargs):
        return {"ok": False, "error": "tool_registry not configured (T13 pending)"}
