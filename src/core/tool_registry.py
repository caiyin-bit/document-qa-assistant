"""Tool registry — name → (schema, tool instance) DI pattern.

Three error layers (chat-borrowed):
  1. Protocol error  — caller asked for an unknown tool name. Returned
     by `execute()` before any tool code runs.
  2. Business error  — tool's own validation/lookup failure. Tools return
     `{ok: False, error: "<code>", message: "..."}` themselves.
  3. System error    — tool raised an unhandled exception. Caught here
     so a failing tool can't crash the assistant loop.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA

log = logging.getLogger(__name__)


class _ToolLike(Protocol):
    async def execute(self, *, session_id: Any, **kwargs: Any) -> dict: ...


ToolEntry = tuple[dict, _ToolLike]


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolEntry]) -> None:
        self._tools = tools

    @classmethod
    def default(
        cls, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
    ) -> "ToolRegistry":
        """V1 wiring: only search_documents.

        Add new tools here as the V2 surface grows. Each entry is
        (raw_schema_dict, tool_instance).
        """
        return cls({
            "search_documents": (
                TOOL_SCHEMA,
                SearchDocumentsTool(
                    mem=mem, embedder=embedder,
                    min_similarity=min_similarity, top_k=top_k,
                    reranker=reranker, rerank_top_n=rerank_top_n,
                ),
            ),
        })

    def schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas wrapped in OpenAI Tools API envelope.

        Some strict gateways (we hit this on a previous SiliconFlow
        deployment) reject calls missing the {type, function} wrapper
        with 400 "Field required". Keep the wrapper unconditionally.
        """
        return [
            {"type": "function", "function": schema}
            for schema, _ in self._tools.values()
        ]

    async def execute(
        self, name: str, arguments: dict, *, session_id,
    ) -> dict:
        entry = self._tools.get(name)
        if not entry:
            log.warning("tool_registry.unknown name=%s", name)
            return {
                "ok": False, "error": "unknown_tool",
                "message": f"unknown tool: {name}",
            }
        _, tool = entry
        try:
            return await tool.execute(session_id=session_id, **arguments)
        except Exception as e:
            log.exception("tool_registry.system_error name=%s", name)
            return {
                "ok": False, "error": "system",
                "message": str(e)[:200],
            }
