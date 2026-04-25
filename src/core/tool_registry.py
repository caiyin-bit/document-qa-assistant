"""ToolRegistry: bundles tool schemas and dispatches LLM tool_calls."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.core.memory_service import MemoryService
from src.tools import complete_todo as t_complete_todo
from src.tools import create_contact as t_create
from src.tools import log_follow_up as t_follow
from src.tools import recall_contact as t_recall
from src.tools import update_user_profile as t_update_profile

log = logging.getLogger(__name__)


ToolFn = Callable[[MemoryService, dict, dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(
        self,
        memory: MemoryService,
        tools: dict[str, tuple[dict, ToolFn]],
    ) -> None:
        self._memory = memory
        self._tools = tools

    @classmethod
    def default(cls, memory: MemoryService) -> "ToolRegistry":
        return cls(
            memory=memory,
            tools={
                "create_contact": (t_create.SCHEMA, t_create.execute_create_contact),
                "log_follow_up": (t_follow.SCHEMA, t_follow.execute_log_follow_up),
                "recall_contact": (t_recall.SCHEMA, t_recall.execute_recall_contact),
                "update_user_profile": (
                    t_update_profile.SCHEMA,
                    t_update_profile.execute_update_user_profile,
                ),
                "complete_todo": (
                    t_complete_todo.SCHEMA,
                    t_complete_todo.execute_complete_todo,
                ),
            },
        )

    def schemas(self) -> list[dict[str, Any]]:
        return [schema for schema, _ in self._tools.values()]

    async def execute(self, name: str, arguments: dict, context: dict) -> dict:
        entry = self._tools.get(name)
        if not entry:
            log.warning("unknown tool requested: %s", name)
            return {
                "ok": False,
                "error": "unknown_tool",
                "message": f"未知工具 {name}",
            }
        _, fn = entry
        try:
            return await fn(self._memory, context, arguments)
        except Exception as e:  # 系统错误兜底
            log.exception("tool %s raised", name)
            return {"ok": False, "error": "system", "message": f"内部错误: {e}"}
