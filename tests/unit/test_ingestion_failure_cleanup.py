import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from src.ingest.ingestion import _ingest_document, _ingest_with_timeout
from src.models.schemas import DocumentStatus


@pytest.mark.asyncio
async def test_midrun_exception_cleans_partial_chunks():
    """Business error during midrun ingestion → mark failed and clean chunks."""
    from src.ingest.pdf_parser import PdfValidationError

    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock(side_effect=[[1.0]*1024, PdfValidationError("boom")])
    parser = lambda path: iter([(1, "p1"), (2, "p2")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=parser, chunker=chunker)

    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    last_call = mem.update_document.await_args_list[-1]
    assert last_call.kwargs.get("status") == DocumentStatus.failed
    assert "boom" in last_call.kwargs.get("error_message", "")


@pytest.mark.asyncio
async def test_timeout_cleans_partial_chunks(monkeypatch):
    mem = MagicMock()
    mem.delete_chunks_for_document = AsyncMock()
    mem.update_document = AsyncMock()

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    # Patch _ingest_document inside ingestion module to be slow
    import src.ingest.ingestion as ing
    monkeypatch.setattr(ing, "_ingest_document", slow)

    await _ingest_with_timeout("doc-id", path=Path("/tmp/x.pdf"),
                                mem=mem, embedder=MagicMock(),
                                iter_pages=lambda p: iter([]),
                                chunker=lambda t, n: [],
                                timeout=0.1)

    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    last = mem.update_document.await_args_list[-1]
    assert last.kwargs.get("status") == DocumentStatus.failed
    assert "超时" in last.kwargs.get("error_message", "")


@pytest.mark.asyncio
async def test_happy_path_marks_ready():
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock(return_value=[[0.1]*1024])
    parser = lambda path: iter([(1, "page one")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=parser, chunker=chunker)

    # No clean call on success
    mem.delete_chunks_for_document.assert_not_awaited()
    # update_document called with status=ready (last call)
    statuses = [c.kwargs.get("status") for c in mem.update_document.await_args_list
                if c.kwargs.get("status") is not None]
    assert statuses[-1] == DocumentStatus.ready


@pytest.mark.asyncio
async def test_infra_error_propagates_for_arq_retry():
    """DB connection errors must NOT be swallowed; Arq retry depends on
    the job function raising for non-business failures."""
    from sqlalchemy.exc import OperationalError

    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock(side_effect=OperationalError("conn", {}, Exception("blip")))
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock(return_value=[[0.0]*1024])
    parser = lambda path: iter([(1, "page text")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    with pytest.raises(OperationalError):
        await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                                mem=mem, embedder=embedder,
                                iter_pages=parser, chunker=chunker)

    # No mark-failed call — Arq should retry
    for c in mem.update_document.await_args_list:
        assert c.kwargs.get("status") != DocumentStatus.failed
    mem.delete_chunks_for_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_validation_error_marks_failed():
    """PdfValidationError is a business error → mark failed and return."""
    from src.ingest.pdf_parser import PdfValidationError

    def bad_parser(path):
        raise PdfValidationError("PDF 损坏")
        yield  # make it a generator
    mem = MagicMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock()

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=bad_parser,
                            chunker=lambda *a, **kw: [])

    last = mem.update_document.await_args_list[-1]
    assert last.kwargs.get("status") == DocumentStatus.failed
    assert "损坏" in last.kwargs.get("error_message", "")
