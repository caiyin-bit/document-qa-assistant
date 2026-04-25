"""Direct unit tests for SSEStreamingResponse.stream_response's finally
hop — Hop 1 of the V2.1.F 3-hop deterministic cleanup chain.

The httpx ASGITransport buffers the full response body before yielding,
so we cannot simulate a real mid-stream client disconnect with that
transport. Instead, we test the finally semantics of the response
subclass directly: regardless of how stream_response exits (normal
completion or exception), the body_iterator must be explicitly aclose'd.
"""

import asyncio

import pytest

from src.api.sse import SSEStreamingResponse


class _TrackingBodyIter:
    """Minimal async iterator that tracks whether aclose() ran."""

    def __init__(self, items: list[bytes]):
        self._items = list(items)
        self.aclose_called = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)

    async def aclose(self):
        self.aclose_called = True


async def _noop_send(message):
    """Fake ASGI send that swallows everything — no real network."""
    pass


async def test_sse_streaming_response_finally_aclose_on_normal_completion():
    """When body iterator naturally exhausts, finally still aclose's it.
    (No-op — already exhausted — but the call must happen.)"""
    body = _TrackingBodyIter([b"chunk1", b"chunk2"])
    resp = SSEStreamingResponse(body, media_type="text/event-stream")
    await resp.stream_response(_noop_send)
    assert body.aclose_called is True


async def test_sse_streaming_response_finally_aclose_on_send_failure():
    """When send fails mid-stream (simulating broken connection), finally
    still aclose's the body iterator. This is the load-bearing claim of
    Hop 1: SSEStreamingResponse.stream_response.finally → body.aclose()
    runs regardless of why the inner code exited."""
    body = _TrackingBodyIter([b"chunk1", b"chunk2", b"chunk3"])
    sent = {"count": 0}

    async def failing_send(message):
        sent["count"] += 1
        if sent["count"] >= 2:
            raise OSError("simulated broken pipe")

    resp = SSEStreamingResponse(body, media_type="text/event-stream")
    with pytest.raises(OSError, match="broken pipe"):
        await resp.stream_response(failing_send)
    # Even though stream_response raised, finally must have aclose'd.
    assert body.aclose_called is True


async def test_sse_streaming_response_finally_aclose_on_cancelled_error():
    """CancelledError mid-stream (the Starlette task-group cancellation
    path) must also trigger finally → aclose."""
    body = _TrackingBodyIter([b"chunk1", b"chunk2"])
    sent = {"count": 0}

    async def cancelling_send(message):
        sent["count"] += 1
        if sent["count"] >= 2:
            raise asyncio.CancelledError()

    resp = SSEStreamingResponse(body, media_type="text/event-stream")
    with pytest.raises(asyncio.CancelledError):
        await resp.stream_response(cancelling_send)
    assert body.aclose_called is True
