import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.conversation_engine import ConversationEngine


@pytest.mark.asyncio
async def test_b_empty_emits_fixed_text_and_empty_citations():
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 0, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=MagicMock(), tools=MagicMock(),
                                 persona="助手")
    events = []
    async for ev in engine.handle_stream(session_id="sid", message="hi"):
        events.append(ev)

    types = [e.type for e in events]
    assert "text" in types and "citations" in types and "done" in types
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "请先上传" in full
    cit = next(e for e in events if e.type == "citations")
    assert cit.data["chunks"] == []


@pytest.mark.asyncio
async def test_b_processing_emits_processing_text():
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 0, "processing": 1, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=MagicMock(), tools=MagicMock(),
                                 persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="hi")]
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "正在解析中" in full


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
        def __init__(self, id, name=None, arguments=None):
            self.id, self.name, self.arguments = id, name, arguments

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                id="t1", name="search_documents", arguments='{"query":"营收"}')])
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
        def __init__(self, id, name=None, arguments=None):
            self.id, self.name, self.arguments = id, name, arguments

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                id="t1", name="search_documents", arguments='{"query":"x"}')])
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
