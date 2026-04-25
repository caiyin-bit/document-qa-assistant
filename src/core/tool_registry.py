"""Stub — replaced by single-tool registry in Task 9."""


class ToolRegistry:
    """Placeholder. Replaced in Task 9."""

    def __init__(self, *args, **kwargs):
        pass

    def schemas(self):
        return []

    async def execute(self, name, arguments, *, session_id=None):
        return {"ok": False, "error": f"tool_registry stub: {name} not registered"}
