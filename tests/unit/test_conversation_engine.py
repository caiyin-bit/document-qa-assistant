import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.conversation_engine import ConversationEngine


async def _run_engine_capturing_tools(counts: dict[str, int]):
    """Drive ConversationEngine with a fake LLM; return (events, captured tools arg)."""
    captured = {}

    class _Chunk:
        def __init__(self, text="", finish=None):
            self.text_delta = text
            self.tool_call_deltas = []
            self.finish_reason = finish

    async def fake_chat_stream(messages, tools):
        captured["tools"] = tools
        yield _Chunk(text="ok")
        yield _Chunk(finish="stop")

    llm = MagicMock(); llm.chat_stream = fake_chat_stream
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value=counts)
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=llm, tools=MagicMock(), persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="hi")]
    return events, captured.get("tools")


@pytest.mark.asyncio
async def test_b_empty_routes_to_plain_llm_without_tools():
    events, tools_arg = await _run_engine_capturing_tools(
        {"ready": 0, "processing": 0, "failed": 0})
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "请先上传" not in full  # no canned message
    assert tools_arg is None       # plain chat, no search tool exposed


@pytest.mark.asyncio
async def test_b_processing_routes_to_plain_llm_without_tools():
    """User must be able to chat freely while docs are still being parsed."""
    events, tools_arg = await _run_engine_capturing_tools(
        {"ready": 0, "processing": 1, "failed": 0})
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "请稍候再提问" not in full
    assert "正在解析中" not in full  # no canned message
    assert tools_arg is None         # plain chat, no search tool exposed


@pytest.mark.asyncio
async def test_b_failed_emits_failed_text():
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 0, "processing": 0, "failed": 1})
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=MagicMock(), tools=MagicMock(),
                                 persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="hi")]
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "解析失败" in full


@pytest.mark.asyncio
async def test_template_a_with_tool_found_true_emits_citations():
    """Mock LLM to call search_documents once, mock tool to return found=true."""
    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        # Mirrors src.llm.gemini_client.ToolCallDelta — only the first delta
        # for a given index carries id/name; later ones append fragments.
        def __init__(self, index, id=None, name=None, arguments_fragment=""):
            self.index = index
            self.id = id
            self.name = name
            self.arguments_fragment = arguments_fragment

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                index=0, id="t1", name="search_documents",
                arguments_fragment='{"query":"营收"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            yield _LLMChunk(text_delta="腾讯 2025 年总营收为 6,605 亿元。")
            yield _LLMChunk(finish_reason="stop")

    llm = MagicMock(); llm.chat_stream = fake_chat_stream

    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value={
        "ok": True, "found": True,
        "chunks": [{"doc_id": "d1", "filename": "x.pdf", "page_no": 12,
                     "snippet": "营收 6605 亿…", "score": 0.85,
                     "content": "营收 6605 亿…全文"}]
    })

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=89,
                  status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    mem.save_tool_message = AsyncMock()

    engine = ConversationEngine(mem=mem, llm=llm, tools=tools, persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="问")]

    cit = next(e for e in events if e.type == "citations")
    assert len(cit.data["chunks"]) == 1
    assert cit.data["chunks"][0]["page_no"] == 12
    # 'content' is stripped from citations (snippet remains)
    assert "content" not in cit.data["chunks"][0]


@pytest.mark.asyncio
async def test_template_a_with_tool_found_false_emits_empty_citations():
    """Tool returns found=false → citations event with chunks=[]."""
    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        # Mirrors src.llm.gemini_client.ToolCallDelta — only the first delta
        # for a given index carries id/name; later ones append fragments.
        def __init__(self, index, id=None, name=None, arguments_fragment=""):
            self.index = index
            self.id = id
            self.name = name
            self.arguments_fragment = arguments_fragment

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                index=0, id="t1", name="search_documents",
                arguments_fragment='{"query":"x"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            yield _LLMChunk(text_delta="在已上传文档中未找到相关信息。")
            yield _LLMChunk(finish_reason="stop")

    llm = MagicMock(); llm.chat_stream = fake_chat_stream
    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value={"ok": True, "found": False, "chunks": []})

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=89, status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()

    engine = ConversationEngine(mem=mem, llm=llm, tools=tools, persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="问")]
    cit = next(e for e in events if e.type == "citations")
    assert cit.data["chunks"] == []


@pytest.mark.asyncio
async def test_template_a_accumulates_fragmented_tool_call_deltas():
    """Real OpenAI streaming sends id+name only on the first delta; later
    deltas share `index` and carry argument fragments only. Engine must
    accumulate by index, not id, or arguments will be lost / split."""
    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        def __init__(self, index, id=None, name=None, arguments_fragment=""):
            self.index, self.id, self.name = index, id, name
            self.arguments_fragment = arguments_fragment

    captured_args: dict = {}

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[
                _ToolDelta(index=0, id="t1", name="search_documents",
                           arguments_fragment='{"que')])
            yield _LLMChunk(tool_call_deltas=[
                _ToolDelta(index=0, arguments_fragment='ry":"营')])
            yield _LLMChunk(tool_call_deltas=[
                _ToolDelta(index=0, arguments_fragment='收"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            yield _LLMChunk(text_delta="6605 亿。")
            yield _LLMChunk(finish_reason="stop")

    async def capture_execute(name, args, *, session_id):
        captured_args["query"] = args.get("query")
        return {"ok": True, "found": False, "chunks": []}

    llm = MagicMock(); llm.chat_stream = fake_chat_stream
    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = capture_execute

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(
        return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=10, status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()

    engine = ConversationEngine(mem=mem, llm=llm, tools=tools, persona="助手")
    [_ async for _ in engine.handle_stream(session_id="sid", message="问")]
    assert captured_args.get("query") == "营收"


@pytest.mark.asyncio
async def test_template_a_falls_back_to_no_tools_when_loop_exhausts():
    """If LLM keeps issuing tool_calls past max_tool_iterations, the engine
    must make one final no-tools call so the user gets text — not a hung
    'thinking' UI with an empty saved assistant message."""
    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        def __init__(self, index, id=None, name=None, arguments_fragment=""):
            self.index, self.id, self.name = index, id, name
            self.arguments_fragment = arguments_fragment

    call_log: list[dict] = []
    counter = {"n": 0}

    async def fake_chat_stream(messages, tools):
        call_log.append({"tools": tools, "msgs": len(messages)})
        counter["n"] += 1
        if tools is not None:
            # Always demand another tool call — simulates a model that
            # keeps searching forever.
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                index=0, id=f"t{counter['n']}", name="search_documents",
                arguments_fragment='{"query":"x"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            # Fallback path: no tools → must answer textually.
            yield _LLMChunk(text_delta="抱歉，多次检索后仍未找到。")
            yield _LLMChunk(finish_reason="stop")

    llm = MagicMock(); llm.chat_stream = fake_chat_stream
    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value={"ok": True, "found": False, "chunks": []})

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(
        return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=10, status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()

    engine = ConversationEngine(
        mem=mem, llm=llm, tools=tools, persona="助手", max_tool_iterations=2,
    )
    events = [e async for e in engine.handle_stream(session_id="sid", message="问")]

    # 2 tool-loop calls + 1 fallback call
    assert len(call_log) == 3
    assert call_log[0]["tools"] is not None
    assert call_log[1]["tools"] is not None
    assert call_log[2]["tools"] is None  # fallback explicitly disables tools

    # User got actual text, not empty
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "抱歉" in full

    # Saved assistant message is non-empty
    saved = mem.save_assistant_message.await_args
    assert saved.args[1] == "抱歉，多次检索后仍未找到。"
