"""Arq job: ingest a single uploaded PDF.

Spec: docs/superpowers/specs/2026-04-26-ingestion-worker-design.md §3.2.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from src.core.memory_service import MemoryService
from src.ingest.chunker import chunk
from src.ingest.ingestion import _ingest_document, _mark_failed_and_clean
from src.ingest.pdf_parser import iter_pages
from src.models.schemas import DocumentStatus

log = logging.getLogger(__name__)

# Constants imported from main so func() in WorkerSettings stays the
# single source of truth (see test_worker_jobs::test_max_tries_constant_consistent).
INGEST_MAX_TRIES = 2
INGEST_TIMEOUT = 1800

UPLOADS_DIR = Path("data/uploads")


async def ingest_document(ctx, doc_id_str: str) -> None:
    """Idempotent ingestion job.

    Step 1: preflight — verify the PDF exists on disk; if not, mark failed
    and return (this is a business error, not retryable).
    Step 2: reset — delete any partial chunks from a previous crashed
    try, reset progress fields.
    Step 3: run — call the existing `_ingest_document` pipeline.
    Cancellation handled at outer try/except so the inner session can
    finish __aexit__ before any fresh-session work runs.
    """
    doc_id = UUID(doc_id_str)
    sm = ctx["sessionmaker"]
    embedder = ctx["embedder"]
    job_try = ctx.get("job_try", 1)
    log.info("event=ingest.start doc_id=%s job_try=%d max_tries=%d",
              doc_id, job_try, INGEST_MAX_TRIES)

    path = UPLOADS_DIR / f"{doc_id}.pdf"
    if not path.is_file():
        async with sm() as db:
            mem = MemoryService(db)
            await mem.update_document(
                doc_id, status=DocumentStatus.failed,
                error_message="上传文件未落盘，请删除后重新上传",
                progress_phase=None,
            )
        log.warning("event=ingest.failed.business doc_id=%s reason=missing_file", doc_id)
        return

    # Step 2: idempotent reset (own session so commit lands before encode loop)
    async with sm() as db:
        mem = MemoryService(db)
        deleted = await mem.delete_chunks_for_document(doc_id)
        await mem.update_document(
            doc_id, status=DocumentStatus.processing,
            progress_page=0, progress_phase=None, error_message=None,
        )
    log.info("event=ingest.reset doc_id=%s deleted_chunks=%s", doc_id, deleted)

    # Step 3: run. CRITICAL ordering: try/except wraps the entire
    # `async with sm()` block, NOT a try inside it. If cancel fires mid
    # bulk_insert_chunks the original session has a pending statement;
    # opening a fresh session inside the still-active `async with` would
    # race with that session's __aexit__ (rollback/close). Wrapping at
    # this level lets the original session fully unwind first.
    try:
        async with sm() as db:
            mem = MemoryService(db)
            await _ingest_document(
                doc_id, path=path, mem=mem, embedder=embedder,
                iter_pages=iter_pages, chunker=chunk,
            )
    except asyncio.CancelledError:
        log.warning("event=ingest.cancelled doc_id=%s job_try=%d last_try=%s",
                     doc_id, job_try, job_try >= INGEST_MAX_TRIES)
        if job_try >= INGEST_MAX_TRIES:
            async def _final_mark_failed():
                async with sm() as fresh:
                    fmem = MemoryService(fresh)
                    await _mark_failed_and_clean(
                        doc_id, "解析多次超时/中断，请删除后重试",
                        mem=fmem,
                    )
            try:
                await asyncio.shield(asyncio.wait_for(
                    _final_mark_failed(), timeout=5.0))
            except Exception:
                log.warning("final mark-failed for %s also failed", doc_id)
        raise
    log.info("event=ingest.ready doc_id=%s", doc_id)
