from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pdfplumber


class PdfValidationError(Exception):
    """Upload-time validation failure (4xx for the API)."""


@dataclass
class PdfMeta:
    page_count: int


def open_pdf_meta(path: Path) -> PdfMeta:
    """Open + validate + return meta. Raises PdfValidationError on:
    - Corrupted/unreadable file → '无法打开 PDF（损坏？）'
    - Encrypted file → 'PDF 已加密'
    - Zero pages → '空 PDF'
    Spec §4.upload.validate
    """
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
    except Exception as e:
        msg = str(e).lower()
        if "encrypt" in msg or "password" in msg:
            raise PdfValidationError("PDF 已加密")
        raise PdfValidationError(f"无法打开 PDF（损坏？）: {e}")
    if n == 0:
        raise PdfValidationError("空 PDF")
    return PdfMeta(page_count=n)


def iter_pages(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (page_no_1based, text). Empty pages yield ''.
    Caller decides whether to skip empty.
    """
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            yield i, page.extract_text() or ""
