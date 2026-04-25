"""System prompt rendering — see spec §4.4."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from src.core.memory_service import ContactRecord, FollowUpRecord, TodoRecord

PROFILE_MAX_CHARS = 200
FOLLOWUP_CONTENT_MAX = 120

_WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def render_system_prompt(
    persona: str,
    contacts: list[ContactRecord],
    recent_follow_ups: dict[UUID, list[FollowUpRecord]],
    user_profile: str | None = None,
    session_summary: str | None = None,
    due_reminders: list[TodoRecord] | None = None,
    now: datetime | None = None,
) -> str:
    parts: list[str] = [persona.strip()]

    current = (now or datetime.now().astimezone())
    parts.append(
        f"\n# 当前时间\n"
        f"{current.strftime('%Y-%m-%d')} {_WEEKDAY_ZH[current.weekday()]} "
        f"{current.strftime('%H:%M %Z').strip()}"
    )

    if user_profile:
        parts.append("\n# 关于你自己(经纪人)")
        parts.append("(关于使用你的经纪人本人的持久记忆,优先级高于对话)")
        parts.append("")
        parts.append(user_profile.strip())

    if contacts:
        parts.append("\n# 上下文(参考,若与当前话题无关可忽略)")
        parts.append("\n## 相关客户")
        for c in contacts:
            header_bits: list[str] = []
            if c.age is not None:
                header_bits.append(f"{c.age}岁")
            if c.occupation:
                header_bits.append(c.occupation)
            if c.family:
                header_bits.append(c.family)
            header = f"({', '.join(header_bits)})" if header_bits else ""
            profile_snippet = _truncate(c.profile_text or "", PROFILE_MAX_CHARS)
            parts.append(f"- {c.name}{header}:{profile_snippet}")

        # 最近跟进
        any_fu = any(recent_follow_ups.get(c.id) for c in contacts)
        if any_fu:
            parts.append("\n## 最近跟进(按时间倒序)")
            # 展平成列表按 occurred_at desc
            flat: list[tuple[FollowUpRecord, str]] = []
            id_to_name = {c.id: c.name for c in contacts}
            for c in contacts:
                for fu in recent_follow_ups.get(c.id, []):
                    flat.append((fu, id_to_name[c.id]))
            flat.sort(key=lambda x: x[0].occurred_at, reverse=True)
            for fu, name in flat:
                ts = fu.occurred_at.strftime("%Y-%m-%d %H:%M")
                content = _truncate(fu.content, FOLLOWUP_CONTENT_MAX)
                parts.append(f"- [{ts}] 对{name}:{content}")

    if session_summary:
        parts.append("\n# 早期对话摘要")
        parts.append("(此前对话已压缩,要点如下)")
        parts.append("")
        parts.append(session_summary.strip())

    if due_reminders:
        parts.append("\n# 待办提醒(已到期)")
        parts.append(
            "(以下事项已过截止时间,处理规则:\n"
            "(1) 本轮回复开头主动告知经纪人,逐条复述时**必须保留 [id: ...] 标记**,"
            "方便后续轮次再次引用;\n"
            "(2) 若经纪人本轮或后续轮次确认完成(如说'做完了'/'已经处理'/'取消'),"
            "**必须调用 complete_todo(todo_id) 工具**,不要只在文本中宣称完成。)"
        )
        parts.append("")
        for t in due_reminders:
            ts = t.due_at.strftime("%Y-%m-%d %H:%M")
            parts.append(f"- [{ts}] {t.title} [id: {t.id}]")

    return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "……"
