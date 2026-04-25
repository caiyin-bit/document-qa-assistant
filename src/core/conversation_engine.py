"""Stub — replaced by full streaming engine in Task 12.

Until then ConversationEngine is a no-op so that src.main + src.api.chat
can be imported and other tasks can reference make_app_default().
"""
from typing import AsyncIterator


class ConversationEngine:
    """Placeholder. Replaced in Task 12."""

    def __init__(self, *, mem=None, llm=None, tools=None, persona: str = ""):
        self.mem = mem
        self.llm = llm
        self.tools = tools
        self.persona = persona

    async def handle(self, *, session_id, message: str) -> str:
        return "(engine stub: implement Task 12)"

    async def handle_stream(self, *, session_id, message: str) -> AsyncIterator:
        # Yield nothing — engine not yet implemented
        if False:
            yield None
