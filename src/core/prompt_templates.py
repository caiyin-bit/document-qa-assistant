"""Spec §6: prompt templates.
A           = ready docs exist → strict RAG (must call search, must cite)
B-EMPTY     = no docs at all   → plain LLM chat (no tool, no citation)
B-PROCESSING= docs ingesting   → fixed canned response (transient state)
B-FAILED    = all docs failed  → fixed canned response (user must clean up)
"""

# Only PROCESSING/FAILED are canned; B-EMPTY now routes to plain LLM chat.
FIXED_RESPONSES = {
    "B-PROCESSING": "文档正在解析中，请稍候再提问。",
    "B-FAILED":     "已上传的文档解析失败，请删除后重新上传。",
    "NO_MATCH":     "在已上传文档中未找到相关信息。",
}


def select_template(counts: dict[str, int]) -> str:
    ready = counts.get("ready", 0)
    processing = counts.get("processing", 0)
    failed = counts.get("failed", 0)
    if ready >= 1:
        return "A"
    if processing >= 1:
        return "B-PROCESSING"
    if failed >= 1:
        return "B-FAILED"
    return "B-EMPTY"


_A_TEMPLATE = """{persona}

你是一个文档问答助手。

【可用文档】
{doc_list}

【行为规则】
1. 任何用户问题都必须先调用 search_documents 工具检索
2. 工具返回 found=false 或 chunks 为空时，必须**完整、原样**回答：
   "{no_match}"
   不要补充猜测、不要解释为什么没找到、不要给替代答案
3. 工具返回 found=true 时，只能基于这些 chunks 的内容作答；
   不得使用你的常识或训练知识补充
4. 不要在回答正文中标注 [1] [2] 这类引用，前端会自动渲染来源卡片
5. 用简洁、专业的中文回答；数字保留报告中的精度
"""

_B_EMPTY_TEMPLATE = """你是一个友好的中文助手。用户尚未上传任何 PDF 文档。

【行为规则】
1. 请直接基于你的知识回答用户的问题，不要调用任何工具
2. 不要假装从文档中检索；不要提及 search_documents 之类的工具
3. 不要主动反复提醒用户"上传 PDF 后可以问 X"——那是 UI 引导的事
4. 用简洁、专业的中文回答；不知道就直接说不知道
"""


def render_system_prompt(template: str, *, docs: list[dict], persona: str) -> str:
    if template == "A":
        doc_lines = "\n".join(
            f"- {d['filename']}（共 {d['page_count']} 页）" for d in docs
        ) or "（无）"
        return _A_TEMPLATE.format(
            persona=persona, doc_list=doc_lines,
            no_match=FIXED_RESPONSES["NO_MATCH"],
        )
    if template == "B-EMPTY":
        # Persona deliberately NOT included — the persona enforces strict
        # PDF-only answering, which is the wrong behavior here.
        return _B_EMPTY_TEMPLATE
    # PROCESSING / FAILED: canned reply path; system prompt is unused but we
    # still return persona for safety in case anything routes to LLM.
    return f"{persona}\n\n（系统提示：{FIXED_RESPONSES[template]}）"
