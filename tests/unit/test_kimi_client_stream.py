"""Tests for KimiClient.chat_stream — streaming chat completion."""

from unittest.mock import AsyncMock

import pytest

from src.llm.kimi_client import (
    Chunk,
    KimiClient,
    LlmCallFailed,
    ToolCallDelta,
)


class _FakeStreamIter:
    """Mimics openai's AsyncStream: async-iterable, `close()` awaits."""

    def __init__(self, raw_chunks: list, raise_after: int | None = None):
        self._chunks = raw_chunks
        self._raise_after = raise_after
        self._i = 0
        self.close_called = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._raise_after is not None and self._i == self._raise_after:
            raise RuntimeError("mid-stream boom")
        if self._i >= len(self._chunks):
            raise StopAsyncIteration
        c = self._chunks[self._i]
        self._i += 1
        return c

    async def close(self):
        self.close_called = True


def _mk_chunk(content=None, tool_calls=None, finish_reason=None):
    """Build an object shaped like openai ChatCompletionChunk enough for tests."""
    class _Delta:
        pass
    class _Choice:
        pass
    class _Chunk:
        pass

    delta = _Delta()
    delta.content = content
    delta.tool_calls = tool_calls

    choice = _Choice()
    choice.delta = delta
    choice.finish_reason = finish_reason

    ch = _Chunk()
    ch.choices = [choice]
    return ch


def _mk_openai_tool_call_delta(index, id=None, name=None, arguments_fragment=None):
    class _Fn:
        pass
    class _TC:
        pass
    fn = _Fn()
    fn.name = name
    fn.arguments = arguments_fragment or ""
    tc = _TC()
    tc.index = index
    tc.id = id
    tc.function = fn
    return tc


async def test_chat_stream_text_only(monkeypatch):
    """3 text delta chunks + final 'stop' → yields 4 Chunks (3 text + 1 finish)."""
    stream_iter = _FakeStreamIter([
        _mk_chunk(content="你好"),
        _mk_chunk(content="世界"),
        _mk_chunk(content="!"),
        _mk_chunk(content=None, finish_reason="stop"),
    ])
    mock_create = AsyncMock(return_value=stream_iter)

    client = KimiClient(openai_client=None, model_id="test-model")
    monkeypatch.setattr(client, "_client", type("X", (), {
        "chat": type("C", (), {
            "completions": type("Cm", (), {
                "create": mock_create,
            })(),
        })(),
    })())

    chunks: list[Chunk] = []
    async for c in client.chat_stream(messages=[{"role": "user", "content": "hi"}], tools=None):
        chunks.append(c)

    text_deltas = [c.text_delta for c in chunks if c.text_delta is not None]
    assert text_deltas == ["你好", "世界", "!"]
    finishes = [c.finish_reason for c in chunks if c.finish_reason]
    assert finishes == ["stop"]


async def test_chat_stream_tool_call_deltas(monkeypatch):
    """tool_call name + arguments arrive across chunks → yielded as ToolCallDelta list."""
    stream_iter = _FakeStreamIter([
        _mk_chunk(tool_calls=[_mk_openai_tool_call_delta(0, id="c1", name="create_contact", arguments_fragment='{"na')]),
        _mk_chunk(tool_calls=[_mk_openai_tool_call_delta(0, arguments_fragment='me":"')]),
        _mk_chunk(tool_calls=[_mk_openai_tool_call_delta(0, arguments_fragment='张三"}')]),
        _mk_chunk(finish_reason="tool_calls"),
    ])
    mock_create = AsyncMock(return_value=stream_iter)

    client = KimiClient(openai_client=None, model_id="test-model")
    monkeypatch.setattr(client, "_client", type("X", (), {
        "chat": type("C", (), {
            "completions": type("Cm", (), {"create": mock_create})(),
        })(),
    })())

    tool_deltas_all: list[ToolCallDelta] = []
    finish = None
    async for c in client.chat_stream(messages=[], tools=None):
        if c.tool_call_deltas:
            tool_deltas_all.extend(c.tool_call_deltas)
        if c.finish_reason:
            finish = c.finish_reason

    # Reassemble: id "c1", name "create_contact", arguments '{"name":"张三"}'
    args = "".join(d.arguments_fragment for d in tool_deltas_all if d.arguments_fragment)
    assert args == '{"name":"张三"}'
    assert any(d.id == "c1" and d.name == "create_contact" for d in tool_deltas_all)
    assert finish == "tool_calls"


async def test_chat_stream_mid_stream_error_propagates(monkeypatch):
    """Error after first chunk → LlmCallFailed; no retry (would replay tokens)."""
    stream_iter = _FakeStreamIter([_mk_chunk(content="hi")], raise_after=1)
    mock_create = AsyncMock(return_value=stream_iter)

    client = KimiClient(openai_client=None, model_id="test-model")
    monkeypatch.setattr(client, "_client", type("X", (), {
        "chat": type("C", (), {
            "completions": type("Cm", (), {"create": mock_create})(),
        })(),
    })())

    with pytest.raises(LlmCallFailed):
        async for _ in client.chat_stream(messages=[], tools=None):
            pass
    # Verify no retry: create was called exactly once
    assert mock_create.call_count == 1
    # Verify stream.close() was called via finally — the upstream HTTP
    # connection must be released even on mid-stream error.
    assert stream_iter.close_called is True, (
        "mid-stream error must still trigger stream.close() via finally"
    )


async def test_chat_stream_no_finish_reason_is_protocol_error(monkeypatch):
    """Stream ends without finish_reason → LlmCallFailed (spec §4.3)."""
    stream_iter = _FakeStreamIter([_mk_chunk(content="hi")])  # no finish
    mock_create = AsyncMock(return_value=stream_iter)

    client = KimiClient(openai_client=None, model_id="test-model")
    monkeypatch.setattr(client, "_client", type("X", (), {
        "chat": type("C", (), {
            "completions": type("Cm", (), {"create": mock_create})(),
        })(),
    })())

    with pytest.raises(LlmCallFailed, match="finish_reason"):
        async for _ in client.chat_stream(messages=[], tools=None):
            pass
