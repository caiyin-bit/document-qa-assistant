"""Ingestion writes documents.progress_phase at each stage so the SSE feed
can tell the frontend whether the slow time is being spent on model load,
text extraction, BGE encoding, or DB insert."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from src.ingest.ingestion import (
    _ingest_document,
    PHASE_LOADING,
    PHASE_EXTRACTING,
    PHASE_EMBEDDING,
    PHASE_INSERTING,
)
from src.models.schemas import DocumentStatus


def _phases_in_order(mem) -> list[str]:
    """Extract the sequence of progress_phase values written via update_document."""
    phases = []
    for c in mem.update_document.await_args_list:
        if "progress_phase" in c.kwargs:
            phases.append(c.kwargs["progress_phase"])
    return phases


@pytest.mark.asyncio
async def test_phase_sequence_for_single_page_with_chunks():
    """One page with content should write: loading → extracting → embedding
    → inserting → (terminal None when status flips to ready)."""
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()

    embedder = MagicMock()
    embedder.embed_batch = MagicMock(return_value=[[0.1] * 1024])

    parser = lambda path: iter([(1, "some content")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    await _ingest_document(
        "doc-id", path=Path("/tmp/x.pdf"),
        mem=mem, embedder=embedder, iter_pages=parser, chunker=chunker,
    )

    phases = _phases_in_order(mem)
    assert phases == [
        PHASE_LOADING,
        PHASE_EXTRACTING,
        PHASE_EMBEDDING,
        PHASE_INSERTING,
        None,  # cleared when status → ready
    ], f"unexpected phase sequence: {phases}"


@pytest.mark.asyncio
async def test_phase_loading_set_before_first_page():
    """The 'loading' phase must be written BEFORE iter_pages is consumed,
    because BGE model lazy-load happens on first embed_batch call. Setting
    it up-front prevents the UI from looking frozen while the model loads."""
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()

    embedder = MagicMock()
    embedder.embed_batch = MagicMock(return_value=[[0.1] * 1024])

    parser = lambda path: iter([(1, "x")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    await _ingest_document(
        "doc-id", path=Path("/tmp/x.pdf"),
        mem=mem, embedder=embedder, iter_pages=parser, chunker=chunker,
    )

    phases = _phases_in_order(mem)
    assert phases[0] == PHASE_LOADING, (
        f"first phase should be 'loading', got {phases[0]}"
    )


@pytest.mark.asyncio
async def test_failure_path_clears_phase():
    """When ingestion fails (scanned PDF / 0 chunks), progress_phase must be
    reset to None so the failed UI doesn't keep showing a stale phase."""
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()

    embedder = MagicMock()
    parser = lambda path: iter([(1, ""), (2, "")])
    chunker = lambda text, page_no: []  # always empty → triggers failed path

    await _ingest_document(
        "doc-id", path=Path("/tmp/x.pdf"),
        mem=mem, embedder=embedder, iter_pages=parser, chunker=chunker,
    )

    failed_calls = [
        c for c in mem.update_document.await_args_list
        if c.kwargs.get("status") == DocumentStatus.failed
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("progress_phase") is None, (
        "failure path must clear progress_phase to None"
    )
