"""Stub — replaced by full implementation in Task 4.

This file exists so that other modules referencing MemoryService can be
imported during the scaffold phase. Don't add real logic here; Task 4
defines the actual class.
"""
from dataclasses import dataclass
from typing import Any


class MemoryService:
    """Placeholder. Replaced in Task 4."""

    def __init__(self, *args, **kwargs):
        pass


@dataclass
class MessageRecord:
    """Placeholder. Replaced in Task 4."""

    role: str
    content: str | None = None
    tool_calls: list[Any] | None = None
