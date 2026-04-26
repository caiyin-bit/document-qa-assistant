"""Unit tests for `ingest_document` Arq job. Uses fake ctx + mocked deps;
no real Redis or Postgres needed (those live in tests/e2e/)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call
from uuid import UUID, uuid4

import pytest


DOC_ID = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def fake_sm(tmp_path):
    """Sessionmaker that yields a MagicMock-shaped 'mem' on each enter."""
    sessions: list = []

    class _Sm:
        def __call__(self):
            mem = MagicMock()
            mem.delete_chunks_for_document = AsyncMock()
            mem.update_document = AsyncMock()
            mem.bulk_insert_chunks = AsyncMock()
            sess = AsyncMock()
            sess.__aenter__ = AsyncMock(return_value=sess)
            sess.__aexit__ = AsyncMock(return_value=None)
            sess._mem = mem  # for assertions
            sessions.append(sess)
            return sess

    sm = _Sm()
    sm.sessions = sessions  # type: ignore[attr-defined]
    return sm


@pytest.fixture
def fake_embedder():
    e = MagicMock()
    e.embed_batch_async = AsyncMock(return_value=[[0.0] * 1024])
    return e


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr("src.worker.jobs.UPLOADS_DIR", d)
    return d


def _make_pdf(uploads_dir: Path, doc_id: UUID) -> Path:
    """Drop a tiny valid-ish PDF stub at uploads/{doc_id}.pdf.
    For unit tests we mock iter_pages so the file just needs to exist."""
    p = uploads_dir / f"{doc_id}.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake\n")
    return p


@pytest.mark.asyncio
async def test_ingest_document_missing_file_marks_failed(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """If uploads/{doc_id}.pdf is missing (e.g. crash between INSERT and
    rename), worker step 2 marks the doc failed with a clear message and
    returns (no Arq retry)."""
    from src.worker.jobs import ingest_document

    # Wire MemoryService(db) → db._mem so we can assert on mock calls
    monkeypatch.setattr("src.worker.jobs.MemoryService", lambda db: db._mem)

    ctx = {
        "sessionmaker": fake_sm,
        "embedder": fake_embedder,
        "job_try": 1,
    }
    # Note: file deliberately NOT created
    await ingest_document(ctx, str(DOC_ID))

    # Exactly one session opened (preflight branch)
    assert len(fake_sm.sessions) == 1
    mem = fake_sm.sessions[0]._mem
    last = mem.update_document.await_args_list[-1]
    from src.models.schemas import DocumentStatus
    assert last.kwargs["status"] == DocumentStatus.failed
    assert "未落盘" in last.kwargs["error_message"]


@pytest.mark.asyncio
async def test_ingest_document_step1_resets_state(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """When file exists, step 1 deletes chunks + resets progress fields
    in its own session BEFORE the run-step session opens."""
    from src.worker.jobs import ingest_document

    _make_pdf(uploads_dir, DOC_ID)

    monkeypatch.setattr("src.worker.jobs.MemoryService", lambda db: db._mem)

    # When _ingest_document runs, the reset-session work must already be
    # complete: its session_index in fake_sm.sessions is 1 (preflight is 0
    # — wait no, preflight only runs if file is missing, so for this test
    # session 0 = reset, session 1 = run).
    sessions_at_run_start = []

    async def fake_ingest(doc_id, *, path, mem, embedder, iter_pages, chunker):
        sessions_at_run_start.append(len(fake_sm.sessions))

    monkeypatch.setattr("src.worker.jobs._ingest_document", fake_ingest)

    ctx = {"sessionmaker": fake_sm, "embedder": fake_embedder, "job_try": 1}
    await ingest_document(ctx, str(DOC_ID))

    # Two sessions opened: [0]=reset, [1]=run
    assert len(fake_sm.sessions) == 2, [s for s in fake_sm.sessions]
    # By the time _ingest_document was invoked, the reset session was
    # already exited (count was 2 because run-session had been entered).
    assert sessions_at_run_start == [2]

    reset_mem = fake_sm.sessions[0]._mem
    assert reset_mem.delete_chunks_for_document.await_count == 1
    reset_call = next(
        c for c in reversed(reset_mem.update_document.await_args_list)
        if c.kwargs.get("progress_page") == 0
    )
    assert reset_call.kwargs.get("progress_phase") is None
    assert reset_call.kwargs.get("error_message") is None

    # And ingestion ran with session[1]'s mem, which has its own (empty) call log
    run_mem = fake_sm.sessions[1]._mem
    assert run_mem.delete_chunks_for_document.await_count == 0


@pytest.mark.asyncio
async def test_ingest_document_happy_path_invokes_ingestion(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """File exists + ingestion succeeds → _ingest_document called with
    correct args."""
    from src.worker.jobs import ingest_document

    # Wire MemoryService(db) → db._mem so we can assert on mock calls
    monkeypatch.setattr("src.worker.jobs.MemoryService", lambda db: db._mem)

    pdf = _make_pdf(uploads_dir, DOC_ID)
    captured_args = {}

    async def fake_ingest(doc_id, *, path, mem, embedder, iter_pages, chunker):
        captured_args.update(
            doc_id=doc_id, path=path, embedder=embedder,
            iter_pages=iter_pages, chunker=chunker,
        )

    monkeypatch.setattr("src.worker.jobs._ingest_document", fake_ingest)

    ctx = {"sessionmaker": fake_sm, "embedder": fake_embedder, "job_try": 1}
    await ingest_document(ctx, str(DOC_ID))

    assert captured_args["doc_id"] == DOC_ID
    assert captured_args["path"] == pdf
    assert captured_args["embedder"] is fake_embedder
