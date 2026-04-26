"""Spec §6 + §7: 4-template dispatch + structured citations binding."""
import asyncio
import json
import logging
from typing import AsyncIterator

# Hard upper bound per LLM iteration. SiliconFlow's HTTP-level keepalives
# can keep the stream "alive" indefinitely without sending any actual
# token chunks, defeating httpx's `read` timeout. We enforce an
# application-level deadline so a stalled stream is forced into the
# fallback path instead of hanging /chat/stream forever.
LLM_ITER_TIMEOUT_S = 120

from src.api.sse import StreamEvent
from src.core.prompt_templates import (
    FIXED_RESPONSES, render_system_prompt, select_template,
)

log = logging.getLogger(__name__)


class ConversationEngine:
    def __init__(
        self, *, mem, llm, tools, persona: str = "",
        max_tool_iterations: int = 3, **_ignored,
    ):
        self.mem = mem
        self.llm = llm
        self.tools = tools
        self.persona = persona
        self.max_tool_iterations = max_tool_iterations

    async def handle_stream(self, *, session_id, message: str, **_ignored) -> AsyncIterator[StreamEvent]:
        import time as _t
        _t0 = _t.monotonic()
        log.info("chat.start session=%s msg_len=%d", session_id, len(message))
        # Persist user message
        await self.mem.save_user_message(session_id, message)

        counts = await self.mem.count_documents_by_status(session_id)
        template = select_template(counts)
        log.info("chat.template=%s elapsed=%.2fs", template, _t.monotonic() - _t0)

        # B-FAILED: canned reply (user must clean up failed docs first).
        # B-EMPTY and B-PROCESSING fall through to plain LLM chat below.
        if template == "B-FAILED":
            fixed = FIXED_RESPONSES[template]
            yield StreamEvent.text(delta=fixed)
            yield StreamEvent.citations(chunks=[])
            await self.mem.save_assistant_message(session_id, fixed, citations=[])
            yield StreamEvent.done()
            return

        # Template A: strict RAG. B-EMPTY / B-PROCESSING: plain chat, no tools.
        if template == "A":
            docs = await self.mem.list_documents(session_id)
            ready_docs = [
                {"filename": d.filename, "page_count": d.page_count}
                for d in docs
                if (d.status.value if hasattr(d.status, "value") else d.status) == "ready"
            ]
            system_prompt = render_system_prompt("A", docs=ready_docs, persona=self.persona)
            tools_for_llm = self.tools.schemas()
        else:
            system_prompt = render_system_prompt(template, docs=[], persona=self.persona)
            tools_for_llm = None

        history = []
        for m in await self.mem.list_messages(session_id):
            entry = {
                "role": m.role.value if hasattr(m.role, "value") else m.role,
                "content": m.content,
            }
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            history.append(entry)

        messages = [{"role": "system", "content": system_prompt}] + history

        collected_chunks: list[dict] = []
        all_found_false = True
        had_any_tool_call = False
        final_text_buf = ""

        loop_finished_with_stop = False
        for _iter in range(self.max_tool_iterations):
            _ti = _t.monotonic()
            log.info("chat.iter=%d llm_call_start elapsed=%.2fs",
                     _iter, _ti - _t0)
            text_buf = ""
            tool_call_acc = {}
            finish_reason = None

            try:
                async with asyncio.timeout(LLM_ITER_TIMEOUT_S):
                    async for chunk in self.llm.chat_stream(messages, tools=tools_for_llm):
                        if chunk.text_delta:
                            text_buf += chunk.text_delta
                            yield StreamEvent.text(delta=chunk.text_delta)
                        for d in (chunk.tool_call_deltas or []):
                            # Per OpenAI streaming protocol: only the first delta
                            # for a given tool-call carries id/name; subsequent
                            # deltas share the same `index` and only carry
                            # argument fragments. So accumulate by index.
                            acc = tool_call_acc.setdefault(
                                d.index, {"id": None, "name": "", "arguments": ""},
                            )
                            if d.id:
                                acc["id"] = d.id
                            if d.name:
                                acc["name"] = d.name
                            if d.arguments_fragment:
                                acc["arguments"] += d.arguments_fragment
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason
            except (asyncio.TimeoutError, TimeoutError):
                log.warning(
                    "chat.iter=%d timeout after %ds, breaking to fallback",
                    _iter, LLM_ITER_TIMEOUT_S,
                )
                finish_reason = "timeout"

            log.info("chat.iter=%d llm_done finish=%s tool_calls=%d elapsed=%.2fs",
                     _iter, finish_reason, len(tool_call_acc), _t.monotonic() - _t0)

            if finish_reason == "stop":
                final_text_buf = text_buf
                messages.append({"role": "assistant", "content": text_buf})
                loop_finished_with_stop = True
                break

            if finish_reason == "tool_calls" and tool_call_acc:
                had_any_tool_call = True
                tc_list = [
                    {"id": acc["id"], "type": "function",
                     "function": {"name": acc["name"], "arguments": acc["arguments"]}}
                    for acc in tool_call_acc.values()
                ]
                messages.append({"role": "assistant", "content": text_buf,
                                  "tool_calls": tc_list})

                for acc in tool_call_acc.values():
                    yield StreamEvent.tool_call_started(
                        tc_id=acc["id"], name=acc["name"],
                    )
                    try:
                        args = json.loads(acc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    _tt = _t.monotonic()
                    result = await self.tools.execute(
                        acc["name"], args, session_id=session_id,
                    )
                    log.info("chat.tool=%s ok=%s found=%s chunks=%d took=%.2fs",
                             acc["name"], result.get("ok"), result.get("found"),
                             len(result.get("chunks") or []), _t.monotonic() - _tt)
                    if acc["name"] == "search_documents" and result.get("ok"):
                        if result.get("found"):
                            all_found_false = False
                            collected_chunks.extend(result.get("chunks", []))
                    yield StreamEvent.tool_call_finished(
                        tc_id=acc["id"], ok=bool(result.get("ok")),
                    )

                    messages.append({
                        "role": "tool", "tool_call_id": acc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue

            break  # finish_reason missing or unexpected

        # Loop exited without `stop` (max iterations reached, or LLM gave up
        # producing tool_calls). Force one final no-tools call so the user
        # gets a textual answer based on what was already retrieved, instead
        # of a stuck "thinking" UI.
        if not loop_finished_with_stop:
            log.info("chat.fallback no-tools final call elapsed=%.2fs",
                        _t.monotonic() - _t0)
            messages.append({
                "role": "system",
                "content": (
                    "你已经检索过相关段落，现在不要再调用任何工具，"
                    "直接基于上面的工具结果用中文给出最终回答。"
                    "如果检索结果不足以回答，明确告知用户。"
                ),
            })
            text_buf = ""
            try:
                async with asyncio.timeout(LLM_ITER_TIMEOUT_S):
                    async for chunk in self.llm.chat_stream(messages, tools=None):
                        if chunk.text_delta:
                            text_buf += chunk.text_delta
                            yield StreamEvent.text(delta=chunk.text_delta)
            except (asyncio.TimeoutError, TimeoutError):
                log.warning("chat.fallback timeout after %ds", LLM_ITER_TIMEOUT_S)
                if not text_buf:
                    text_buf = "（超时未能生成回答，请重试或换个问法）"
                    yield StreamEvent.text(delta=text_buf)
            final_text_buf = text_buf

        # Citations decision (spec §7 structured signal)
        if not had_any_tool_call or all_found_false:
            citations = []
        else:
            citations = [
                {k: v for k, v in c.items() if k != "content"}
                for c in collected_chunks
            ]

        # De-dupe on (doc_id, page_no)
        seen = set()
        unique_citations = []
        for c in citations:
            key = (c["doc_id"], c["page_no"])
            if key in seen:
                continue
            seen.add(key)
            unique_citations.append(c)

        await self.mem.save_assistant_message(
            session_id, final_text_buf, citations=unique_citations,
        )
        yield StreamEvent.citations(chunks=unique_citations)
        log.info("chat.done text_len=%d citations=%d total=%.2fs",
                 len(final_text_buf), len(unique_citations), _t.monotonic() - _t0)
        yield StreamEvent.done()
