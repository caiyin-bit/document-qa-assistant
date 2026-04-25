"""Stub — replaced by full streaming engine in Task 12.

Until then ConversationEngine is a no-op so that src.main + src.api.chat
can be imported and other tasks can reference make_app_default().
"""
from typing import AsyncIterator


class ConversationEngine:
    """Placeholder. Replaced in Task 12."""

    def __init__(self, *args, **kwargs):
        pass

    async def handle(self, *args, **kwargs) -> str:
        return "(engine stub: implement Task 12)"

    async def handle_stream(self, *args, **kwargs) -> AsyncIterator:
        # Yield nothing — engine not yet implemented
        if False:
            yield None
