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
