from src.ingest.chunker import chunk

# Use a deterministic mock token counter: 1 char = 1 token (simplifies math)
import src.ingest.chunker as ch
ch._token_count = len  # type: ignore   # see implementation note in Step 4


def test_case_1_blank_page():
    assert chunk("", page_no=1) == []
    assert chunk("   \n\n  \n", page_no=1) == []

def test_case_2_short_paragraph():
    out = chunk("第一段。", page_no=5)
    assert len(out) == 1
    assert out[0].page_no == 5
    assert "第一段" in out[0].content

def test_case_3_exactly_500():
    para = "x" * 500
    out = chunk(para, page_no=1)
    assert len(out) == 1
    assert len(out[0].content) == 500

def test_case_4_multiple_aggregated_with_overlap():
    p1 = "x" * 400
    p2 = "y" * 200   # 400 + 200 = 600 > 500 → split, 80 char overlap
    text = p1 + "\n\n" + p2
    out = chunk(text, page_no=1)
    assert len(out) >= 2
    assert all(len(c.content) <= 500 for c in out)
    assert out[0].content[-80:] in out[1].content or "x" in out[1].content

def test_case_5_oversized_single_paragraph_split_by_sentences():
    sentences = "。".join(["a" * 200] * 5) + "。"
    out = chunk(sentences, page_no=1)
    assert all(len(c.content) <= 500 for c in out)
    assert len(out) >= 2

def test_case_6_tail_plus_para_degrades():
    p1 = "x" * 450
    p2 = "y" * 480
    out = chunk(p1 + "\n\n" + p2, page_no=1)
    assert all(len(c.content) <= 500 for c in out)

def test_case_7_oversized_single_sentence_sliding_window():
    out = chunk("z" * 1500, page_no=1)
    assert all(len(c.content) <= 500 for c in out)
    assert len(out) >= 3

def test_case_8_split_oversized_candidate_overflow():
    long_para = ("a" * 480 + "。") * 3
    out = chunk(long_para, page_no=1)
    assert all(len(c.content) <= 500 for c in out)


def test_page_no_carried():
    out = chunk("一些内容。", page_no=42)
    assert out[0].page_no == 42
