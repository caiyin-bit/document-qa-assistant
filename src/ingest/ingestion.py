"""Ingestion pipeline. Spec §4 (ingestion + startup recovery)."""
import asyncio
import logging
from pathlib import Path
from typing import Callable, Iterable

from src.models.schemas import DocumentStatus

log = logging.getLogger(__name__)


async def _mark_failed_and_clean(doc_id, error_message: str, *, mem) -> None:
    """Single failure-handling path: delete partial chunks then mark failed.
    Used by exception, total_chunks==0, and timeout. Spec §4.

    Callers reach us via cancellation or a raised DB error, both of which
    can leave the session's transaction in an invalid state. Roll back
    first so the cleanup statements don't trip PendingRollbackError.
    """
    try:
        await mem.db.rollback()
    except Exception:
        log.warning("rollback before failure cleanup failed for %s", doc_id)
    await mem.delete_chunks_for_document(doc_id)
    await mem.update_document(
        doc_id,
        status=DocumentStatus.failed,
        error_message=error_message[:500],
        progress_page=0,
        progress_phase=None,
    )


# Phase tags written to documents.progress_phase. The progress SSE surfaces
# these to the frontend so the user can see *why* an ingestion is taking time
# (model load is the slowest stage on first run).
PHASE_LOADING = "loading"      # importing torch / loading BGE into memory
PHASE_EXTRACTING = "extracting"  # pdfplumber.extract_text on a page
PHASE_EMBEDDING = "embedding"    # BGE encode_batch on a page's chunks
PHASE_INSERTING = "inserting"    # bulk INSERT chunks into pgvector


async def _ingest_document(
    doc_id, *, path: Path, mem, embedder,
    iter_pages: Callable[[Path], Iterable[tuple[int, str]]],
    chunker: Callable[[str, int], list],
) -> None:
    """Run full ingestion. On any error, calls _mark_failed_and_clean.

    Updates documents.progress_phase at every stage so the SSE polling on
    /progress can surface granular UI states ("loading" → "extracting" →
    "embedding" → "inserting") rather than a single "ingesting" that often
    looks frozen during BGE encode.
    """
    chunk_idx = 0
    total_chunks = 0
    try:
        # Mark "loading" up-front so the UI shows a non-frozen state during
        # the first BGE call (which lazily loads the ~1GB model into memory
        # — can take 15-30s on first ingestion).
        await mem.update_document(doc_id, progress_phase=PHASE_LOADING)

        for page_no, text in iter_pages(path):
            await mem.update_document(
                doc_id,
                progress_phase=PHASE_EXTRACTING,
                progress_page=page_no,
            )
            chunks = chunker(text, page_no=page_no)
            if chunks:
                # Normalize: support both dict and Chunk dataclass
                contents = [
                    c["content"] if isinstance(c, dict) else c.content
                    for c in chunks
                ]
                await mem.update_document(doc_id, progress_phase=PHASE_EMBEDDING)
                embeddings = embedder.embed_batch(contents)

                await mem.update_document(doc_id, progress_phase=PHASE_INSERTING)
                rows = []
                for i, (c, emb) in enumerate(zip(chunks, embeddings)):
                    content = c["content"] if isinstance(c, dict) else c.content
                    rows.append({
                        "page_no": page_no,
                        "chunk_idx": chunk_idx + i,
                        "content": content,
                        "embedding": emb if isinstance(emb, list) else (list(emb) if hasattr(emb, "__iter__") else emb),
                        "token_count": len(content),
                    })
                await mem.bulk_insert_chunks(doc_id, rows)
                chunk_idx += len(chunks)
                total_chunks += len(chunks)

        if total_chunks == 0:
            await _mark_failed_and_clean(
                doc_id, "未能从 PDF 中提取任何文本（疑似扫描版或纯图像 PDF）",
                mem=mem,
            )
            return

        await mem.update_document(
            doc_id, status=DocumentStatus.ready, progress_phase=None,
        )
    except Exception as e:
        await _mark_failed_and_clean(doc_id, str(e), mem=mem)
        log.exception("ingestion failed for %s", doc_id)


async def _ingest_with_timeout(
    doc_id, *, path: Path, mem, embedder, iter_pages, chunker,
    timeout: float = 300.0,
) -> None:
    try:
        await asyncio.wait_for(
            _ingest_document(doc_id, path=path, mem=mem, embedder=embedder,
                              iter_pages=iter_pages, chunker=chunker),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await _mark_failed_and_clean(
            doc_id, f"解析超时（>{int(timeout/60)} 分钟）", mem=mem,
        )


async def cleanup_stale_documents(mem) -> None:
    """Startup hook (spec §4 'a'): for each processing doc, delete its chunks
    then mark failed with '解析中断'.
    """
    from sqlalchemy import select
    from src.models.schemas import Document
    result = await mem.db.execute(
        select(Document).where(Document.status == DocumentStatus.processing)
    )
    stale = result.scalars().all()
    for doc in stale:
        await mem.delete_chunks_for_document(doc.id)
        await mem.update_document(
            doc.id,
            status=DocumentStatus.failed,
            error_message="解析中断（服务重启），请删除后重新上传",
            progress_page=0,
        )
