"""Summarizer: LLM-only session history compression.

Takes a list of MessageRecord (optionally preceded by a prior summary) and
returns a structured 5-section markdown summary. No DB access; purely a
wrapper around KimiClient with strict output contract.

See spec §5.
"""

from __future__ import annotations

import json

from src.core.memory_service import MessageRecord
from src.llm.kimi_client import KimiClient, LlmResponse


SYSTEM_PROMPT = """你是一个对话历史压缩助手。把以下保险经纪人与助手的对话历史压缩为简洁摘要,
严格按 5 段 markdown 输出:

# 提到的客户
- <名字>(<画像要点>):<一句话>
- ...

# 业务事件
- <经纪人和助手讨论了什么 / 决定了什么>
- ...

# 待办与承诺
- <谁> <做什么> <什么时候>
- ...

# 客户偏好与异议
- <客户名或经纪人> <偏好或反对意见>
- ...

# 其他
<不属于以上四类但应记住的事项;无可省略此段>

要求:
- 客户名字、数字、日期、承诺必须保留
- 经纪人和助手的客气话、确认语忽略
- 模糊判断有疑问的事实,以"经纪人提到 X"开头(不下结论)
- 已有的旧摘要里的事实仍要保留
- 输出纯 markdown,不要前后任何解释性文字
- 控制在 1000 token 以内
"""


class Summarizer:
    def __init__(self, llm: KimiClient) -> None:
        self._llm = llm

    async def summarize(
        self,
        prior_summary: str | None,
        messages: list[MessageRecord],
    ) -> str:
        user_content = _render_user_prompt(prior_summary, messages)
        prompt = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        resp: LlmResponse = await self._llm.chat(prompt, tools=None)

        if resp.tool_calls:
            raise ValueError(
                "summarizer LLM unexpectedly returned tool_calls: "
                f"{[tc.name for tc in resp.tool_calls]}"
            )
        if resp.content is None:
            raise ValueError("summarizer LLM returned content=None")

        return resp.content.strip()


def _render_user_prompt(
    prior_summary: str | None, messages: list[MessageRecord]
) -> str:
    parts: list[str] = []
    if prior_summary:
        parts.append(prior_summary.strip())
        parts.append("---")
    parts.append("以下是要压缩的新对话(按时间顺序):")
    for m in messages:
        parts.append(_render_one(m))
    return "\n".join(parts)


def _render_one(m: MessageRecord) -> str:
    if m.role == "user":
        return f"用户: {m.content or ''}"
    if m.role == "assistant":
        if m.tool_calls:
            calls = ", ".join(
                f"{tc['name']}({json.dumps(tc['arguments'], ensure_ascii=False)})"
                for tc in m.tool_calls
            )
            return f"助手调用工具 {calls}"
        return f"助手: {m.content or ''}"
    if m.role == "tool":
        return f"工具返回: {m.content or ''}"
    return f"{m.role}: {m.content or ''}"
