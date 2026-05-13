from src.core.prompt_templates import (
    select_template, render_system_prompt, FIXED_RESPONSES,
)


def test_fixed_responses_match_spec_exact():
    # Only B-FAILED stays canned; B-EMPTY and B-PROCESSING route to LLM chat.
    assert FIXED_RESPONSES["B-FAILED"] == "已上传的文档解析失败，请删除后重新上传。"
    assert FIXED_RESPONSES["NO_MATCH"] == "在已上传文档中未找到相关信息。"
    assert "B-EMPTY" not in FIXED_RESPONSES
    assert "B-PROCESSING" not in FIXED_RESPONSES


def test_select_template_a_when_ready_geq_1():
    assert select_template({"ready": 1, "processing": 0, "failed": 0}) == "A"
    assert select_template({"ready": 1, "processing": 1, "failed": 1}) == "A"


def test_select_template_b_empty_when_no_docs():
    assert select_template({"ready": 0, "processing": 0, "failed": 0}) == "B-EMPTY"


def test_select_template_b_processing_when_has_processing_no_ready():
    assert select_template({"ready": 0, "processing": 1, "failed": 0}) == "B-PROCESSING"
    # mix: processing + failed → still B-PROCESSING per spec
    assert select_template({"ready": 0, "processing": 1, "failed": 2}) == "B-PROCESSING"


def test_select_template_b_failed_when_only_failed():
    assert select_template({"ready": 0, "processing": 0, "failed": 1}) == "B-FAILED"


def test_render_template_a_includes_filenames():
    docs = [{"filename": "x.pdf", "page_count": 10}]
    p = render_system_prompt("A", docs=docs, persona="你是助手")
    assert "你是助手" in p
    assert "x.pdf" in p and "10" in p
    assert "search_documents" in p


def test_render_template_b_empty_omits_persona_and_signals_no_docs():
    p = render_system_prompt("B-EMPTY", docs=[], persona="你是助手")
    # Persona deliberately omitted — it would over-constrain plain chat.
    assert "你是助手" not in p
    assert "尚未上传" in p


def test_render_template_b_processing_hints_at_parsing_in_progress():
    p = render_system_prompt("B-PROCESSING", docs=[], persona="你是助手")
    assert "解析中" in p


def test_tool_usage_rules_block_is_exported_and_present_in_A():
    """The tool-usage rules must be a named constant and embedded in template A."""
    from src.core.prompt_templates import (
        _TOOL_USAGE_RULES, render_system_prompt,
    )

    # It's a non-trivial multi-line block of rules.
    assert "search_documents" in _TOOL_USAGE_RULES
    assert _TOOL_USAGE_RULES.count("\n") >= 5

    rendered = render_system_prompt(
        "A",
        docs=[{"filename": "test.pdf", "page_count": 3}],
        persona="P",
    )
    # The block appears verbatim in template-A output.
    assert _TOOL_USAGE_RULES.strip() in rendered


def test_tool_usage_rules_absent_from_B_templates():
    """B-EMPTY / B-PROCESSING must NOT embed the tool-usage rules block."""
    from src.core.prompt_templates import _TOOL_USAGE_RULES, render_system_prompt

    for tpl in ("B-EMPTY", "B-PROCESSING"):
        rendered = render_system_prompt(tpl, docs=[], persona="P")
        # The full rules block must not appear (B-* templates use plain
        # chat — no search tool wired up). B-EMPTY's own body mentions
        # "search_documents" only to tell the model NOT to use it, so we
        # match on a distinctive substring of the rules block instead.
        assert _TOOL_USAGE_RULES.strip() not in rendered
        assert "多组件问题必须发起多次 search" not in rendered


def test_tool_usage_rules_no_match_matches_fixed_responses():
    """Guard against drift: the NO_MATCH text quoted inside _TOOL_USAGE_RULES
    must stay byte-identical to FIXED_RESPONSES["NO_MATCH"]. Both live in
    src/core/prompt_templates.py; this asserts that they agree."""
    from src.core.prompt_templates import _TOOL_USAGE_RULES, FIXED_RESPONSES
    assert FIXED_RESPONSES["NO_MATCH"] in _TOOL_USAGE_RULES, (
        f"NO_MATCH text drifted: FIXED_RESPONSES has "
        f"{FIXED_RESPONSES['NO_MATCH']!r} but _TOOL_USAGE_RULES does not "
        "contain it. Update both, or move to .format(no_match=...) injection."
    )
