"""Spec §6 + §7: 4-template dispatch + structured citations binding."""
import json
import logging
from typing import AsyncIterator

from src.api.sse import StreamEvent
from src.core.prompt_templates import (
    FIXED_RESPONSES, render_system_prompt, select_template,
)

log = logging.getLogger(__name__)


class ConversationEngine:
    def __init__(self, *, mem, llm, tools, persona: str = "", **_ignored):
        self.mem = mem
        self.llm = llm
        self.tools = tools
        self.persona = persona

    async def handle_stream(self, *, session_id, message: str, **_ignored) -> AsyncIterator[StreamEvent]:
        # Persist user message
        await self.mem.save_user_message(session_id, message)

        counts = await self.mem.count_documents_by_status(session_id)
        template = select_template(counts)

        if template != "A":
            fixed = FIXED_RESPONSES[template]
            yield StreamEvent.text(delta=fixed)
            yield StreamEvent.citations(chunks=[])
            await self.mem.save_assistant_message(session_id, fixed, citations=[])
            yield StreamEvent.done()
            return

        # Template A
        docs = await self.mem.list_documents(session_id)
        ready_docs = [
            {"filename": d.filename, "page_count": d.page_count}
            for d in docs
            if (d.status.value if hasattr(d.status, "value") else d.status) == "ready"
        ]
        system_prompt = render_system_prompt("A", docs=ready_docs, persona=self.persona)

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

        for _ in range(5):
            text_buf = ""
            tool_call_acc = {}
            finish_reason = None

            async for chunk in self.llm.chat_stream(messages, tools=self.tools.schemas()):
                if chunk.text_delta:
                    text_buf += chunk.text_delta
                    yield StreamEvent.text(delta=chunk.text_delta)
                for d in (chunk.tool_call_deltas or []):
                    acc = tool_call_acc.setdefault(d.id, {"name": d.name or "", "arguments": ""})
                    if d.name:
                        acc["name"] = d.name
                    if d.arguments:
                        acc["arguments"] += d.arguments
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

            if finish_reason == "stop":
                final_text_buf = text_buf
                messages.append({"role": "assistant", "content": text_buf})
                break

            if finish_reason == "tool_calls" and tool_call_acc:
                had_any_tool_call = True
                tc_list = [
                    {"id": tid, "type": "function",
                     "function": {"name": acc["name"], "arguments": acc["arguments"]}}
                    for tid, acc in tool_call_acc.items()
                ]
                messages.append({"role": "assistant", "content": text_buf,
                                  "tool_calls": tc_list})

                for tid, acc in tool_call_acc.items():
                    yield StreamEvent.tool_call_started(tc_id=tid, name=acc["name"])
                    try:
                        args = json.loads(acc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await self.tools.execute(acc["name"], args, session_id=session_id)
                    if acc["name"] == "search_documents" and result.get("ok"):
                        if result.get("found"):
                            all_found_false = False
                            collected_chunks.extend(result.get("chunks", []))
                    yield StreamEvent.tool_call_finished(tc_id=tid, ok=bool(result.get("ok")))

                    messages.append({
                        "role": "tool", "tool_call_id": tid,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue

            break  # finish_reason missing or unexpected

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
        yield StreamEvent.done()
