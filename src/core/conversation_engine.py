"""ConversationEngine main loop — see spec §7."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from src.api.sse import StreamEvent
from src.core.memory_service import MemoryService, REMINDERS_MAX_PER_ROUND, SessionContext
from src.core.persona_loader import PersonaLoader
from src.core.prompt_templates import render_system_prompt
from src.core.tool_registry import ToolRegistry
from src.llm.kimi_client import KimiClient, LlmResponse, ToolCall, ToolCallDelta

log = logging.getLogger(__name__)


class ConversationError(Exception):
    pass


class ConversationEngine:
    def __init__(
        self,
        memory: MemoryService,
        persona: PersonaLoader,
        tools: ToolRegistry,
        llm: KimiClient,
        summarizer,  # duck-typed (parallels embedder/llm in ChatDependencies)
        *,
        max_tool_iterations: int,
        compress_trigger_threshold: int,
        compress_keep_recent: int,
        retrieve_top_k: int,
        similarity_threshold: float,
    ) -> None:
        self._memory = memory
        self._persona = persona
        self._tools = tools
        self._llm = llm
        self._summarizer = summarizer
        self._max_tool_iterations = max_tool_iterations
        self._compress_trigger_threshold = compress_trigger_threshold
        self._compress_keep_recent = compress_keep_recent
        self._retrieve_top_k = retrieve_top_k
        self._similarity_threshold = similarity_threshold

    async def _prepare_round(
        self, user_id: UUID, session_id: str | UUID, user_message: str
    ) -> tuple[list[dict], SessionContext, list[UUID]]:
        """Steps 0-2 of /chat: compress → load → render.

        Returns (messages, ctx, reminder_ids). The reminder_ids are the
        todo ids rendered into the prompt's `# 待办提醒` section; the
        caller MUST call mark_todos_shown(reminder_ids) inside its
        per-/chat transaction so the shown_at write is atomic with the
        round (rolls back on failure → todos resurface next round).
        """
        await self._memory.compress_if_needed(
            session_id=session_id,
            summarizer=self._summarizer,
            trigger_threshold=self._compress_trigger_threshold,
            keep_recent=self._compress_keep_recent,
        )
        ctx = await self._memory.load_session_context(
            session_id, fallback_limit=self._compress_trigger_threshold
        )
        user_profile = await self._memory.load_user_profile(user_id)
        due_reminders = await self._memory.list_due_reminders(
            user_id, limit=REMINDERS_MAX_PER_ROUND
        )
        relevant_contacts = await self._memory.retrieve_relevant_contacts(
            user_id=user_id,
            query=user_message,
            top_k=self._retrieve_top_k,
            similarity_threshold=self._similarity_threshold,
        )
        recent_fu: dict = {}
        for c in relevant_contacts:
            recent_fu[c.id] = await self._memory.recent_follow_ups_for_contact(
                c.id, limit=2
            )
        system_prompt = render_system_prompt(
            persona=self._persona.load(),
            contacts=relevant_contacts,
            recent_follow_ups=recent_fu,
            user_profile=user_profile,
            session_summary=ctx.summary,
            due_reminders=due_reminders,
        )
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(m.to_llm_format() for m in ctx.messages)
        messages.append({"role": "user", "content": user_message})
        return messages, ctx, [t.id for t in due_reminders]

    async def handle(
        self, user_id: UUID, session_id: str | UUID, user_message: str
    ) -> str:
        """Process one /chat round.

        Step ordering matters:
          0-2. _prepare_round: compress + load + render (best-effort; DB
               failures in compress bubble up; compress LLM failures are
               caught into FAILED and the fallback_limit path continues).
          3. Atomic round (transaction): save user msg + tool-call loop +
             final assistant msg. Any exception rolls back the whole round.
        """
        messages, _ctx, reminder_ids = await self._prepare_round(
            user_id, session_id, user_message
        )

        async with self._memory.transaction():
            await self._memory.save_message(
                session_id, role="user", content=user_message
            )
            if reminder_ids:
                await self._memory.mark_todos_shown(reminder_ids)

            for iteration in range(self._max_tool_iterations):
                response: LlmResponse = await self._llm.chat(
                    messages=messages, tools=self._tools.schemas()
                )

                if response.tool_calls:
                    messages.append(response.to_assistant_message())
                    await self._memory.save_message(
                        session_id,
                        role="assistant",
                        content=response.content,
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in response.tool_calls
                        ],
                    )
                    for call in response.tool_calls:
                        result = await self._tools.execute(
                            call.name, call.arguments, context={"user_id": user_id}
                        )
                        result_json = json.dumps(result, ensure_ascii=False)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": result_json,
                            }
                        )
                        await self._memory.save_message(
                            session_id,
                            role="tool",
                            content=result_json,
                            tool_call_id=call.id,
                        )
                    continue  # next LLM iteration

                # No tool_call → final reply, save and return
                await self._memory.save_message(
                    session_id, role="assistant", content=response.content
                )
                return response.content or ""

            raise ConversationError("tool iteration exceeded")

    async def handle_stream(
        self, user_id: UUID, session_id: str | UUID, user_message: str
    ) -> AsyncIterator["StreamEvent"]:
        """Streaming variant of handle().

        Critical invariants (see spec §5.1, §7.2):
          - `done` is yielded ONLY AFTER the transaction has committed
            (client never sees "success" on a non-persisted write).
          - llm_iter is explicitly aclose'd in a try/finally around the
            async-for loop (Python async-gen aclose does not cascade; we
            must drive KimiClient.stream.close() ourselves).
          - Cancel / GeneratorExit rolls back the whole round via
            transaction's `except BaseException`.
        """
        messages, _ctx, reminder_ids = await self._prepare_round(
            user_id, session_id, user_message
        )
        completed_normally = False

        async with self._memory.transaction():
            await self._memory.save_message(
                session_id, role="user", content=user_message
            )
            if reminder_ids:
                await self._memory.mark_todos_shown(reminder_ids)

            for _iteration in range(self._max_tool_iterations):
                text_buf: list[str] = []
                tool_call_acc: dict[int, _AccumulatedToolCall] = {}
                finish_reason: str | None = None

                llm_iter = self._llm.chat_stream(
                    messages=messages, tools=self._tools.schemas()
                )
                try:
                    async for chunk in llm_iter:
                        if chunk.text_delta:
                            text_buf.append(chunk.text_delta)
                            yield StreamEvent.text(chunk.text_delta)
                        if chunk.tool_call_deltas:
                            for d in chunk.tool_call_deltas:
                                _accumulate(tool_call_acc, d)
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason
                finally:
                    aclose = getattr(llm_iter, "aclose", None)
                    if aclose is not None:
                        await aclose()

                full_text = "".join(text_buf) or None

                if finish_reason == "stop":
                    await self._memory.save_message(
                        session_id, role="assistant", content=full_text or ""
                    )
                    completed_normally = True
                    break

                if finish_reason == "tool_calls":
                    if not tool_call_acc:
                        raise ConversationError(
                            "LLM finish_reason=tool_calls but no tool_call deltas accumulated"
                        )
                    tool_calls = [
                        _finalize(acc)
                        for acc in sorted(tool_call_acc.values(), key=lambda x: x.index)
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": full_text,
                        "tool_calls": [
                            {"id": tc.id, "type": "function",
                             "function": {"name": tc.name,
                                          "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                            for tc in tool_calls
                        ],
                    })
                    await self._memory.save_message(
                        session_id, role="assistant",
                        content=full_text,
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in tool_calls
                        ],
                    )
                    for call in tool_calls:
                        yield StreamEvent.tool_call_started(call.id, call.name)
                        result = await self._tools.execute(
                            call.name, call.arguments, context={"user_id": user_id}
                        )
                        yield StreamEvent.tool_call_finished(
                            call.id, bool(result.get("ok", False))
                        )
                        result_json = json.dumps(result, ensure_ascii=False)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result_json,
                        })
                        await self._memory.save_message(
                            session_id, role="tool",
                            content=result_json, tool_call_id=call.id,
                        )
                    continue  # next LLM iteration

                raise ConversationError(
                    f"unexpected finish_reason={finish_reason!r}"
                )

            else:
                raise ConversationError("tool iteration exceeded")

        # Transaction committed. Only NOW tell the client.
        if completed_normally:
            yield StreamEvent.done()


@dataclass
class _AccumulatedToolCall:
    index: int
    id: str = ""
    name: str = ""
    arguments_buf: str = ""


def _accumulate(acc: dict[int, _AccumulatedToolCall], delta: ToolCallDelta) -> None:
    entry = acc.setdefault(delta.index, _AccumulatedToolCall(index=delta.index))
    if delta.id:
        entry.id = delta.id
    if delta.name:
        entry.name = delta.name
    if delta.arguments_fragment:
        entry.arguments_buf += delta.arguments_fragment


def _finalize(acc: _AccumulatedToolCall) -> ToolCall:
    try:
        args = json.loads(acc.arguments_buf) if acc.arguments_buf else {}
    except json.JSONDecodeError:
        log.warning("tool_call accumulated arguments not valid JSON: %r", acc.arguments_buf)
        args = {}
    return ToolCall(id=acc.id, name=acc.name, arguments=args)
