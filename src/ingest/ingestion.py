"""Ingestion pipeline. Spec §4 (ingestion + startup recovery)."""
import asyncio
import logging
from pathlib import Path
from typing import Callable, Iterable

from src.models.schemas import DocumentStatus

log = logging.getLogger(__name__)


async def _mark_failed_and_clean(doc_id, error_message: str, *, mem) -> None:
    """Single failure-handling path: delete partial chunks then mark failed.
    Used by exception, total_chunks==0, and timeout. Spec §4."""
    await mem.delete_chunks_for_document(doc_id)
    await mem.update_document(
        doc_id,
        status=DocumentStatus.failed,
        error_message=error_message[:500],
        progress_page=0,
    )


async def _ingest_document(
    doc_id, *, path: Path, mem, embedder,
    iter_pages: Callable[[Path], Iterable[tuple[int, str]]],
    chunker: Callable[[str, int], list],
) -> None:
    """Run full ingestion. On any error, calls _mark_failed_and_clean.
    chunker returns list of {content, page_no} dicts or Chunk objects;
    this function adds chunk_idx + embedding fields.
    """
    chunk_idx = 0
    total_chunks = 0
    try:
        for page_no, text in iter_pages(path):
            chunks = chunker(text, page_no=page_no)
            if chunks:
                # Normalize: support both dict and Chunk dataclass
                contents = [
                    c["content"] if isinstance(c, dict) else c.content
                    for c in chunks
                ]
                embeddings = embedder.embed_batch(contents)
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
            await mem.update_document(doc_id, progress_page=page_no)

        if total_chunks == 0:
            await _mark_failed_and_clean(
                doc_id, "未能从 PDF 中提取任何文本（疑似扫描版或纯图像 PDF）",
                mem=mem,
            )
            return

        await mem.update_document(doc_id, status=DocumentStatus.ready)
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
        await _mark_failed_and_clean(doc_id, "解析超时（>5 分钟）", mem=mem)


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
