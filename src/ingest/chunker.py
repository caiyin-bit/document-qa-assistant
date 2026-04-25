from dataclasses import dataclass
from typing import Iterator
import re


MAX_TOKENS = 500
OVERLAP_TOKENS = 80


@dataclass
class Chunk:
    content: str
    page_no: int


def _token_count(s: str) -> int:
    """Char count is a workable proxy for Chinese-heavy text (1 CJK char ≈ 1 token).
    Tests monkey-patch this to len() for determinism. Production uses a tokenizer
    only if we observe drift; YAGNI for V1.
    """
    return len(s)


def _split_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    # Chinese punctuation + newline. Keep delimiters attached to preceding sentence.
    parts = re.split(r"(?<=[。！？\n])", text)
    return [p for p in parts if p.strip()]


def _take_tail_tokens(s: str, n: int) -> str:
    return s[-n:] if len(s) > n else s


def chunk(text: str, page_no: int) -> list[Chunk]:
    """Per spec §4: ≤500 token, 80 overlap, page-bounded."""
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(Chunk(content=buf.strip(), page_no=page_no))
        buf = ""

    for para in paragraphs:
        para_tokens = _token_count(para)

        if para_tokens > MAX_TOKENS:
            flush()
            for piece in _split_oversized(para, MAX_TOKENS, OVERLAP_TOKENS):
                chunks.append(Chunk(content=piece, page_no=page_no))
            continue

        if _token_count(buf) + para_tokens <= MAX_TOKENS:
            buf += ("\n\n" if buf else "") + para
            continue

        # Overflow → flush current, start new with overlap
        tail = _take_tail_tokens(buf, OVERLAP_TOKENS)
        flush()
        candidate = (tail + "\n\n" + para) if tail else para
        if _token_count(candidate) > MAX_TOKENS:
            # Degrade: drop overlap, start fresh with para (known ≤ MAX)
            buf = para
        else:
            buf = candidate

    flush()
    return chunks


def _split_oversized(text: str, max_tokens: int, overlap: int) -> Iterator[str]:
    """Spec §4 _split_oversized: sentence-first, sliding-window fallback,
    candidate-overflow degrade."""
    sentences = _split_sentences(text)
    buf = ""
    for s in sentences:
        if _token_count(s) > max_tokens:
            if buf.strip():
                yield buf.strip()
                buf = ""
            for i in range(0, _token_count(s), max_tokens - overlap):
                yield s[i : i + max_tokens]
            continue
        if _token_count(buf) + _token_count(s) <= max_tokens:
            buf += s
        else:
            if buf.strip():
                yield buf.strip()
            # candidate may overflow when s is near-max + overlap; degrade to bare s
            candidate = _take_tail_tokens(buf, overlap) + s
            buf = candidate if _token_count(candidate) <= max_tokens else s
    if buf.strip():
        yield buf.strip()
