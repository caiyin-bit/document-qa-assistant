from pathlib import Path
import pytest
from src.ingest.pdf_parser import (
    PdfValidationError, _table_to_markdown, iter_pages, open_pdf_meta,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
FIXTURE = FIXTURES / "sample_zh.pdf"
EMPTY_FIXTURE = FIXTURES / "sample_empty.pdf"


def test_open_pdf_meta_returns_page_count():
    meta = open_pdf_meta(FIXTURE)
    assert meta.page_count == 3


def test_open_pdf_meta_rejects_corrupt(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(PdfValidationError, match="无法打开"):
        open_pdf_meta(bad)


def test_open_pdf_meta_rejects_empty():
    # sample_empty.pdf is a valid PDF structure with 0 pages (built by build_sample_pdf.py)
    with pytest.raises(PdfValidationError, match="空 PDF"):
        open_pdf_meta(EMPTY_FIXTURE)


def test_iter_pages_yields_chinese_text():
    pages = list(iter_pages(FIXTURE))
    assert len(pages) == 3
    page_no, text = pages[0]
    assert page_no == 1
    assert "腾讯" in text and "6,605 亿元" in text


def test_table_to_markdown_basic():
    table = [["指标", "2024", "2025"], ["总收入", "5,800", "6,605"]]
    md = _table_to_markdown(table)
    assert md.splitlines() == [
        "| 指标 | 2024 | 2025 |",
        "|---|---|---|",
        "| 总收入 | 5,800 | 6,605 |",
    ]


def test_table_to_markdown_empty_returns_empty():
    assert _table_to_markdown([]) == ""
    assert _table_to_markdown([[]]) == ""


def test_table_to_markdown_handles_none_and_pipe_and_newline():
    table = [["A", "B"], [None, "x|y\nz"]]
    md = _table_to_markdown(table)
    # None → empty cell; pipe escaped; newline → space.
    assert md.splitlines()[2] == "|  | x\\|y z |"


def test_table_to_markdown_pads_short_rows_to_header_width():
    table = [["A", "B", "C"], ["only-one"]]
    md = _table_to_markdown(table)
    assert md.splitlines()[2] == "| only-one |  |  |"
