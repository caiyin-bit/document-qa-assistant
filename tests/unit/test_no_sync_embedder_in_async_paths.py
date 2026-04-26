"""Static guard: in async ingestion / chat / search paths, BGE encode
must go through the *_async methods. Bare embedder.embed_batch /
encode_one calls would silently re-block the event loop."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
ASYNC_FILES = [
    ROOT / "src/ingest/ingestion.py",
    ROOT / "src/api/chat.py",
    ROOT / "src/tools/search_documents.py",
    ROOT / "src/worker/jobs.py",
]
SYNC_CALL = re.compile(
    r"\b(embedder|self\.embedder)\.(embed_batch|encode_one|embed)\("
)


@pytest.mark.parametrize("path", ASYNC_FILES, ids=lambda p: p.name)
def test_no_sync_embedder_calls(path: Path):
    text = path.read_text()
    matches = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        if SYNC_CALL.search(line):
            matches.append(f"{path.name}:{line_no}: {line.strip()}")
    assert not matches, "Sync embedder API used in async path:\n" + "\n".join(matches)
