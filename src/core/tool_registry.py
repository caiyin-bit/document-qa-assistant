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
from typing import TYPE_CHECKING, Any, Protocol

from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA

if TYPE_CHECKING:
    from src.tools.integration_tools import IntegrationToolDeps

log = logging.getLogger(__name__)


class _ToolLike(Protocol):
    async def execute(self, *, session_id: Any, **kwargs: Any) -> dict: ...


ToolEntry = tuple[dict, _ToolLike]


class ToolRegistry:
    def __init__(
        self, tools: dict[str, ToolEntry],
        *, admin_only: set[str] | None = None,
    ) -> None:
        self._tools = tools
        self._admin_only = admin_only or set()

    @classmethod
    def default(
        cls, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
        integration_deps: "IntegrationToolDeps | None" = None,
    ) -> "ToolRegistry":
        tools: dict[str, ToolEntry] = {
            "search_documents": (
                TOOL_SCHEMA,
                SearchDocumentsTool(
                    mem=mem, embedder=embedder,
                    min_similarity=min_similarity, top_k=top_k,
                    reranker=reranker, rerank_top_n=rerank_top_n,
                ),
            ),
        }
        admin_only: set[str] = set()
        if integration_deps is not None:
            from src.tools.integration_tools import build_integration_tools
            for name, schema, tool in build_integration_tools(integration_deps):
                tools[name] = (schema, tool)
                admin_only.add(name)
        return cls(tools, admin_only=admin_only)

    def schemas(self, *, is_admin: bool = False) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": schema}
            for name, (schema, _) in self._tools.items()
            if is_admin or name not in self._admin_only
        ]

    async def execute(
        self, name: str, arguments: dict, *, session_id,
        user_id=None, is_admin: bool = False,
    ) -> dict:
        entry = self._tools.get(name)
        if not entry:
            log.warning("tool_registry.unknown name=%s", name)
            return {
                "ok": False, "error": "unknown_tool",
                "message": f"unknown tool: {name}",
            }
        if name in self._admin_only and not is_admin:
            log.warning("tool_registry.forbidden name=%s user=%s", name, user_id)
            return {
                "ok": False, "error": "forbidden",
                "message": f"admin only: {name}",
            }
        _, tool = entry
        try:
            return await tool.execute(
                session_id=session_id, user_id=user_id, **arguments,
            )
        except TypeError:
            # Tools that don't accept user_id (e.g. search_documents) —
            # call without it for backward compatibility.
            try:
                return await tool.execute(session_id=session_id, **arguments)
            except Exception as e:
                log.exception("tool_registry.system_error name=%s", name)
                return {"ok": False, "error": "system", "message": str(e)[:200]}
        except Exception as e:
            log.exception("tool_registry.system_error name=%s", name)
            return {"ok": False, "error": "system", "message": str(e)[:200]}
