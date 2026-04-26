"""Traditional ↔ Simplified Chinese normalisation.

Why this exists: this corpus contains Hong Kong / Taiwan annual reports
written in 繁體 (`總收入`, `腾讯` vs `騰訊` etc), but users naturally type
queries in 簡體 (`总收入`, `腾讯`). Without normalisation:
  - pg_trgm: char-level trigrams of `总收入` and `總收入` share zero
    characters → keyword recall completely misses traditional content.
  - BGE-large-zh: trained on simplified-heavy data; cosine alignment
    between simp query and trad passage is noticeably weaker.

Strategy: normalise to **simplified** at both ingestion-time (stored
content + embedding input) and query-time (search keyword + embedded
query). After this, both indices and queries live in one form, so
exact-substring (pg_trgm) and semantic (BGE) recall both work
regardless of the source PDF's script.

Snippet shown in the citation card is also simplified — fine for
Chinese readers; the original PDF stays intact on disk for download.
"""

from __future__ import annotations

from zhconv import convert


def to_simplified(text: str) -> str:
    """Convert text to Simplified Chinese (`zh-cn` locale).

    No-op for ASCII / already-simplified input. Pure-Python (no native
    deps), and idempotent.
    """
    if not text:
        return text
    return convert(text, "zh-cn")
