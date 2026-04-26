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


def _table_to_markdown(table: list[list[str | None]]) -> str:
    """Render a 2D pdfplumber table as GitHub-flavored markdown.

    Row 0 is treated as the header. Cells with internal newlines or pipes
    are sanitised so the resulting markdown is well-formed and the
    column/row structure survives chunking + embedding (the LLM can then
    actually align numeric values to their headers).
    """
    if not table or not table[0]:
        return ""

    def _clean(cell: str | None) -> str:
        if cell is None:
            return ""
        return cell.replace("\n", " ").replace("|", "\\|").strip()

    header = [_clean(c) for c in table[0]]
    width = len(header)
    if width == 0:
        return ""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * width) + "|",
    ]
    for row in table[1:]:
        cells = [_clean(c) for c in row]
        if len(cells) < width:
            cells += [""] * (width - len(cells))
        elif len(cells) > width:
            cells = cells[:width]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def iter_pages(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (page_no_1based, text). Empty pages yield ''.

    For pages containing tables, `extract_text()` flattens cells into the
    reading-order prose (column structure is lost). To preserve table
    structure for retrieval we additionally call `extract_tables()` and
    append each table as markdown after the prose. There's some content
    overlap with the flattened prose, but the markdown form lets the LLM
    align values to their column headers.
    """
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            try:
                tables = page.extract_tables() or []
            except Exception:
                # Malformed table layout — fall back to prose only.
                tables = []
            md_blocks: list[str] = []
            for j, t in enumerate(tables, start=1):
                md = _table_to_markdown(t)
                if md:
                    md_blocks.append(f"### 表 {j}\n\n{md}")
            if md_blocks:
                text = (text + "\n\n" + "\n\n".join(md_blocks)).strip()
            yield i, text
