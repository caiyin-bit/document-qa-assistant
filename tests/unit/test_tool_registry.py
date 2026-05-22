"""ToolRegistry behavioral tests: protocol/business/system error layers."""
from __future__ import annotations

import pytest

from src.core.tool_registry import ToolRegistry


class _StubTool:
    def __init__(self, return_value=None, raise_exc=None):
        self.return_value = return_value
        self.raise_exc = raise_exc
        self.called_with = None

    async def execute(self, *, session_id, **kwargs):
        self.called_with = {"session_id": session_id, **kwargs}
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_value


@pytest.mark.asyncio
async def test_schemas_wraps_each_schema_in_function_envelope():
    schema = {"name": "do_thing", "description": "x", "parameters": {}}
    reg = ToolRegistry({"do_thing": (schema, _StubTool())})
    assert reg.schemas() == [{"type": "function", "function": schema}]


@pytest.mark.asyncio
async def test_execute_dispatches_by_name_and_passes_session_id():
    tool = _StubTool(return_value={"ok": True, "answer": 42})
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, tool)})
    out = await reg.execute("do_thing", {"q": "hi"}, session_id="sess-1")
    assert out == {"ok": True, "answer": 42}
    assert tool.called_with == {"session_id": "sess-1", "user_id": None, "q": "hi"}


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_structured_protocol_error():
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, _StubTool())})
    out = await reg.execute("missing_tool", {}, session_id="s")
    assert out == {
        "ok": False, "error": "unknown_tool",
        "message": "unknown tool: missing_tool",
    }


@pytest.mark.asyncio
async def test_execute_tool_exception_returns_structured_system_error():
    tool = _StubTool(raise_exc=RuntimeError("db connection lost"))
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, tool)})
    out = await reg.execute("do_thing", {}, session_id="s")
    assert out["ok"] is False
    assert out["error"] == "system"
    assert "db connection lost" in out["message"]


@pytest.mark.asyncio
async def test_admin_only_tool_hidden_and_blocked_for_non_admin():
    schema = {"name": "secret_tool", "description": "x", "parameters": {}}
    reg = ToolRegistry(
        {"secret_tool": (schema, _StubTool(return_value={"ok": True}))},
        admin_only={"secret_tool"},
    )
    # hidden from schema list for non-admin
    assert reg.schemas(is_admin=False) == []
    assert reg.schemas(is_admin=True) == [
        {"type": "function", "function": schema}
    ]
    # blocked at execute for non-admin
    out = await reg.execute("secret_tool", {}, session_id="s",
                            user_id="u", is_admin=False)
    assert out == {"ok": False, "error": "forbidden",
                   "message": "admin only: secret_tool"}
    out2 = await reg.execute("secret_tool", {}, session_id="s",
                             user_id="u", is_admin=True)
    assert out2 == {"ok": True}


@pytest.mark.asyncio
async def test_default_factory_wires_search_documents():
    """The default factory should produce a working registry for the V1 toolset."""
    from src.tools.search_documents import TOOL_SCHEMA

    class _FakeMem:
        async def search_chunks_hybrid(self, *a, **k): return []
        async def search_chunks(self, *a, **k): return []
    class _FakeEmbedder:
        async def encode_one_async(self, q): return [0.0] * 1024

    reg = ToolRegistry.default(
        mem=_FakeMem(), embedder=_FakeEmbedder(),
        min_similarity=0.5, top_k=20, reranker=None, rerank_top_n=5,
    )
    schemas = reg.schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == TOOL_SCHEMA["name"]
