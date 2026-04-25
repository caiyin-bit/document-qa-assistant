"""Tests for SSE transport layer."""

import asyncio
import json

import pytest

from src.api.sse import StreamEvent, encode_sse, to_sse_bytes


def test_encode_sse_format_all_event_types():
    """Each event type encodes to valid SSE wire frame:
       event: <type>\ndata: <json>\n\n
    """
    frames = {
        "text": encode_sse(StreamEvent.text("你好")),
        "tool_call_started": encode_sse(StreamEvent.tool_call_started("call_a", "create_contact")),
        "tool_call_finished": encode_sse(StreamEvent.tool_call_finished("call_a", True)),
        "done": encode_sse(StreamEvent.done()),
        "error": encode_sse(StreamEvent.error(message="boom", code="LlmCallFailed")),
    }

    for typ, frame in frames.items():
        assert frame.endswith(b"\n\n"), f"{typ} missing SSE terminator"
        text = frame.decode("utf-8")
        assert text.startswith(f"event: {typ}\n"), f"{typ} missing event header"
        data_line = [ln for ln in text.split("\n") if ln.startswith("data: ")][0]
        payload = json.loads(data_line[len("data: "):])
        # Content-sanity checks per event type
        if typ == "text":
            assert payload == {"delta": "你好"}  # ensure_ascii=False
        if typ == "tool_call_started":
            assert payload == {"id": "call_a", "name": "create_contact"}
        if typ == "tool_call_finished":
            assert payload == {"id": "call_a", "ok": True}
        if typ == "done":
            assert payload == {}
        if typ == "error":
            assert payload == {"message": "boom", "code": "LlmCallFailed"}


async def test_to_sse_bytes_exception_yields_error_event_and_closes_events():
    """Plain Exception from generator → emit `event: error` final frame.
       AND explicitly aclose() the events iterator in finally."""
    closed = {"called": False}

    async def bad_gen():
        try:
            yield StreamEvent.text("before")
            raise RuntimeError("boom")
        finally:
            closed["called"] = True

    events_iter = bad_gen()
    frames: list[bytes] = []
    async for f in to_sse_bytes(events_iter):
        frames.append(f)

    assert any(b"event: text" in f for f in frames)
    # Error event must be emitted (last)
    assert any(b"event: error" in f and b"RuntimeError" in f for f in frames)
    # The inner generator MUST have been explicitly aclose'd (finally ran)
    assert closed["called"] is True


async def test_to_sse_bytes_cancelled_error_propagates_and_closes_events():
    """CancelledError → NOT captured as event: error; propagates out.
       AND explicitly aclose() the events iterator in finally."""
    closed = {"called": False}

    async def cancelling_gen():
        try:
            yield StreamEvent.text("before")
            raise asyncio.CancelledError()
        finally:
            closed["called"] = True

    events_iter = cancelling_gen()

    async def consume():
        async for _ in to_sse_bytes(events_iter):
            pass

    with pytest.raises(asyncio.CancelledError):
        await consume()
    # Even though cancelled, finally must have aclose'd the inner gen
    assert closed["called"] is True


def test_citations_event_encoding():
    chunks = [
        {"doc_id": "abc", "filename": "腾讯.pdf", "page_no": 12,
         "snippet": "营业收入 6,605 亿…", "score": 0.83},
    ]
    ev = StreamEvent.citations(chunks=chunks)
    raw = encode_sse(ev)
    assert raw.startswith(b"event: citations\n")
    payload = raw.split(b"data: ", 1)[1].strip()
    parsed = json.loads(payload)
    assert parsed["chunks"][0]["page_no"] == 12


def test_citations_event_empty_chunks():
    ev = StreamEvent.citations(chunks=[])
    raw = encode_sse(ev)
    assert b"event: citations" in raw
    assert b'"chunks": []' in raw or b'"chunks":[]' in raw
