"""Spec §6: prompt templates A / B-EMPTY / B-PROCESSING / B-FAILED."""

FIXED_RESPONSES = {
    "B-EMPTY":      "请先上传 PDF 文档以开始提问。",
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


def render_system_prompt(template: str, *, docs: list[dict], persona: str) -> str:
    if template == "A":
        doc_lines = "\n".join(
            f"- {d['filename']}（共 {d['page_count']} 页）" for d in docs
        ) or "（无）"
        return _A_TEMPLATE.format(
            persona=persona, doc_list=doc_lines,
            no_match=FIXED_RESPONSES["NO_MATCH"],
        )
    # B-* templates: persona + the fixed sentence is the full assistant reply,
    # but we still pass a system prompt so persona stays consistent if anything
    # ever does call the LLM with template B.
    return f"{persona}\n\n（系统提示：{FIXED_RESPONSES[template]}）"
