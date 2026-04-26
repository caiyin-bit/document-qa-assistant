"""Backend startup hook: re-enqueue any ingestion that was in-flight
when the previous backend died.

Spec: docs/superpowers/specs/2026-04-26-ingestion-worker-design.md §5.3.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.models.schemas import Document, DocumentStatus

log = logging.getLogger(__name__)


async def reenqueue_processing_documents(
    *, arq_pool: Any, sessionmaker: async_sessionmaker
) -> None:
    """For every doc with status='processing', enqueue with deterministic
    _job_id. Arq dedupes against any in-flight job for the same id, so
    this is safe to call even when a worker is currently consuming.

    Crucially: this function does NOT touch chunks or doc state — the
    worker's job step-1 owns idempotent cleanup. Touching state here
    would race with a still-running worker job.
    """
    async with sessionmaker() as db:
        result = await db.execute(
            select(Document.id).where(Document.status == DocumentStatus.processing)
        )
        ids = [r[0] for r in result.all()]
    log.info("event=ingest.reaper.scan count=%d", len(ids))

    for doc_id in ids:
        job_id = f"ingest:{doc_id}"
        try:
            job = await arq_pool.enqueue_job(
                "ingest_document", str(doc_id), _job_id=job_id,
            )
            outcome = "queued" if job is not None else "deduped"
        except Exception as e:  # don't let a bad doc kill the whole sweep
            outcome = "redis_error"
            log.error("event=ingest.reaper.enqueue doc_id=%s job_id=%s result=%s err=%s",
                       doc_id, job_id, outcome, e)
            continue
        log.info("event=ingest.reaper.enqueue doc_id=%s job_id=%s result=%s",
                  doc_id, job_id, outcome)
