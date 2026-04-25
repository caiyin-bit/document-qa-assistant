"""Kimi (Moonshot / SiliconFlow) LLM client wrapping AsyncOpenAI.

Moonshot / SiliconFlow 都兼容 OpenAI chat.completions 协议,
我们直接用 AsyncOpenAI 客户端,把 base_url / api_key 指向对应服务.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    RetryError,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolCallDelta:
    """One increment toward a complete ToolCall. Multiple deltas with the
    same `index` accumulate into one final ToolCall.
    """
    index: int
    id: str | None = None
    name: str | None = None
    arguments_fragment: str = ""


@dataclass
class Chunk:
    """One yielded item from chat_stream. Any combination of fields may be
    set on a single chunk — e.g. the final chunk often carries both
    finish_reason and the last text_delta. Engine handles each field
    independently. Stream MUST end with at least one chunk carrying
    finish_reason (else KimiClient raises LlmCallFailed).
    """
    text_delta: str | None = None
    tool_call_deltas: list[ToolCallDelta] | None = None
    finish_reason: str | None = None


@dataclass
class LlmResponse:
    content: str | None
    tool_calls: list[ToolCall]

    def to_assistant_message(self) -> dict:
        """Convert back to OpenAI-format assistant message for the next turn."""
        if self.tool_calls:
            return {
                "role": "assistant",
                "content": self.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in self.tool_calls
                ],
            }
        return {"role": "assistant", "content": self.content}


class LlmCallFailed(Exception):
    pass


class KimiClient:
    def __init__(
        self,
        openai_client: AsyncOpenAI,
        model_id: str,
        max_retries: int = 3,
    ) -> None:
        self._client = openai_client
        self._model_id = model_id
        self._max_retries = max_retries

    @classmethod
    def from_config(cls, base_url: str, api_key: str, model_id: str) -> "KimiClient":
        return cls(
            openai_client=AsyncOpenAI(base_url=base_url, api_key=api_key),
            model_id=model_id,
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LlmResponse:
        payload: dict = {
            "model": self._model_id,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, max=4),
                reraise=True,
            ):
                with attempt:
                    raw = await self._client.chat.completions.create(**payload)
        except RetryError as e:
            raise LlmCallFailed(str(e)) from e
        except Exception as e:
            raise LlmCallFailed(str(e)) from e

        msg = raw.choices[0].message
        tool_calls: list[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                raw_args = tc.function.arguments
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    log.warning("tool_call arguments not valid JSON: %r", raw_args)
                    parsed = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=parsed)
                )

        return LlmResponse(content=msg.content, tool_calls=tool_calls)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream chat completion as Chunks.

        Wraps openai client's stream=True mode. Tenacity retries connection
        establishment 3 times; once first chunk is yielded, mid-stream errors
        propagate as LlmCallFailed (no auto-retry — partial token replay is
        semantically wrong).

        Caller MUST consume to completion or call aclose(); the finally
        block here calls stream.close() to release the upstream connection.
        """
        payload: dict = {
            "model": self._model_id,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=0.5, max=4),
                reraise=True,
            ):
                with attempt:
                    stream = await self._client.chat.completions.create(**payload)
        except RetryError as e:
            raise LlmCallFailed(str(e)) from e
        except Exception as e:
            raise LlmCallFailed(str(e)) from e

        saw_finish_reason = False
        try:
            async for raw in stream:
                text_delta: str | None = None
                tc_deltas: list[ToolCallDelta] | None = None
                finish_reason: str | None = None

                choice = raw.choices[0] if raw.choices else None
                if choice is not None:
                    delta = getattr(choice, "delta", None)
                    if delta is not None:
                        text_delta = getattr(delta, "content", None)
                        raw_tool_calls = getattr(delta, "tool_calls", None)
                        if raw_tool_calls:
                            tc_deltas = []
                            for t in raw_tool_calls:
                                fn = getattr(t, "function", None)
                                tc_deltas.append(ToolCallDelta(
                                    index=t.index,
                                    id=getattr(t, "id", None),
                                    name=getattr(fn, "name", None) if fn else None,
                                    arguments_fragment=getattr(fn, "arguments", "") or "",
                                ))
                    finish_reason = getattr(choice, "finish_reason", None)

                if finish_reason:
                    saw_finish_reason = True

                if text_delta or tc_deltas or finish_reason:
                    yield Chunk(
                        text_delta=text_delta,
                        tool_call_deltas=tc_deltas,
                        finish_reason=finish_reason,
                    )
        except LlmCallFailed:
            raise
        except Exception as e:
            raise LlmCallFailed(str(e)) from e
        finally:
            # Explicit close so cancel / mid-stream-error both release the
            # upstream HTTP connection. openai AsyncStream is NOT a context
            # manager — must call close() explicitly.
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass  # Best-effort during cleanup; don't mask original error

        if not saw_finish_reason:
            raise LlmCallFailed("stream ended without finish_reason")
