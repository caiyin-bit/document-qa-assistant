"""Loads IDENTITY.md + SOUL.md into a concatenated prompt prefix.

Cached on first load; call reload() to pick up file edits.
"""

from __future__ import annotations

from pathlib import Path


class PersonaLoader:
    def __init__(self, identity_path: Path | str, soul_path: Path | str) -> None:
        self._identity_path = Path(identity_path)
        self._soul_path = Path(soul_path)
        self._cached: str | None = None

    def load(self) -> str:
        if self._cached is None:
            identity = self._identity_path.read_text(encoding="utf-8").strip()
            soul = self._soul_path.read_text(encoding="utf-8").strip()
            self._cached = f"{identity}\n\n{soul}"
        return self._cached

    def reload(self) -> None:
        self._cached = None
