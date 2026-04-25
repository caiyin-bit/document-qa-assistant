import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from src.ingest.ingestion import _ingest_document
from src.models.schemas import DocumentStatus


def _approx(needle):
    """Helper: substring matcher for assert_any_await kwargs."""
    class _A:
        def __eq__(self, other): return needle in str(other)
    return _A()


@pytest.mark.asyncio
async def test_scanned_pdf_marks_failed():
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    parser = lambda path: iter([(1, ""), (2, ""), (3, "")])
    chunker = lambda text, page_no: []

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=parser, chunker=chunker)

    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    # Look for the update_document call with status=failed and the scanned message
    failed_calls = [
        c for c in mem.update_document.await_args_list
        if c.kwargs.get("status") == DocumentStatus.failed
    ]
    assert len(failed_calls) == 1
    assert "未能从 PDF 中提取" in failed_calls[0].kwargs.get("error_message", "")
