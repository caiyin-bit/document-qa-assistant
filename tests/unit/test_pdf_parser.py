from pathlib import Path
import pytest
from src.ingest.pdf_parser import open_pdf_meta, iter_pages, PdfValidationError

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
