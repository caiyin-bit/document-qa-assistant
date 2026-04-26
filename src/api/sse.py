"""SSE (Server-Sent Events) transport for /chat/stream.

Contains:
- StreamEvent dataclass: engine-produced events (text / tool_call_* / done / error)
- encode_sse: serialize one StreamEvent to SSE wire bytes
- to_sse_bytes: async-gen adapter that emits bytes to StreamingResponse; its
  finally explicitly closes the upstream engine generator so transaction
  rollback and GeminiClient stream.close run promptly (not via GC).
- SSEStreamingResponse: Starlette StreamingResponse subclass that explicitly
  aclose's its body_iterator in stream_response's finally — the ONLY way
  to guarantee deterministic cleanup on client disconnect in Starlette 1.x.

See spec §6, §7.2.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from starlette.responses import StreamingResponse


@dataclass
class StreamEvent:
    type: str
    data: dict

    @classmethod
    def text(cls, delta: str) -> "StreamEvent":
        return cls(type="text", data={"delta": delta})

    @classmethod
    def tool_call_started(cls, tc_id: str, name: str) -> "StreamEvent":
        return cls(type="tool_call_started", data={"id": tc_id, "name": name})

    @classmethod
    def tool_call_finished(cls, tc_id: str, ok: bool) -> "StreamEvent":
        return cls(type="tool_call_finished", data={"id": tc_id, "ok": ok})

    @classmethod
    def done(cls) -> "StreamEvent":
        return cls(type="done", data={})

    @classmethod
    def error(cls, message: str, code: str = "error") -> "StreamEvent":
        return cls(type="error", data={"message": message, "code": code})

    @classmethod
    def citations(cls, chunks: list[dict]) -> "StreamEvent":
        return cls(type="citations", data={"chunks": chunks})


def encode_sse(event: StreamEvent) -> bytes:
    """Encode one StreamEvent as an SSE wire frame per W3C spec."""
    payload = json.dumps(event.data, ensure_ascii=False)
    return f"event: {event.type}\ndata: {payload}\n\n".encode("utf-8")


async def to_sse_bytes(
    events: AsyncIterator[StreamEvent],
) -> AsyncIterator[bytes]:
    """Adapt engine's StreamEvent iterator → bytes for StreamingResponse.

    Exception handling:
      - Plain Exception: catch, emit `event: error`, best-effort.
      - BaseException (CancelledError / GeneratorExit): DO NOT catch;
        propagate up so SSEStreamingResponse.stream_response's finally can
        explicitly aclose us.

    CRITICAL — finally's `await events.aclose()`:
      Python async-gen semantics: closing THIS outer generator does NOT
      automatically close the inner generator `events` that we iterate via
      `async for`. We must aclose it explicitly — otherwise the engine
      generator would be left suspended at its yield point, never running
      its transaction rollback.
    """
    try:
        async for ev in events:
            yield encode_sse(ev)
    except Exception as e:
        try:
            yield encode_sse(StreamEvent.error(message=str(e), code=type(e).__name__))
        except Exception:
            pass  # client already gone — best effort
    finally:
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            await aclose()


class SSEStreamingResponse(StreamingResponse):
    """StreamingResponse with deterministic body-iterator cleanup.

    Starlette 1.0's native StreamingResponse does NOT explicitly aclose
    the body iterator on task cancellation (client disconnect via
    listen_for_disconnect → task_group.cancel_scope.cancel()). Cleanup
    relies on Python GC — indeterministic.

    We need the engine generator (via to_sse_bytes) to receive GeneratorExit
    at its yield promptly on disconnect so:
      (a) MemoryService.transaction() rollback runs, and
      (b) GeminiClient.chat_stream's try/finally stream.close() fires.

    This subclass guarantees that by explicitly aclose'ing the body_iterator
    in stream_response's finally block.
    """

    async def stream_response(self, send) -> None:
        try:
            await super().stream_response(send)
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                await aclose()
