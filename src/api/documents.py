"""Documents API. Spec §4 (upload + temp/atomic rename + cleanup invariants)."""
import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.memory_service import MemoryService, DEMO_USER_ID
from src.db.session import get_db, _get_default_sm
from src.embedding.bge_embedder import BgeEmbedder
from src.ingest.chunker import chunk
from src.ingest.ingestion import _ingest_with_timeout
from src.ingest.pdf_parser import iter_pages, open_pdf_meta, PdfValidationError

log = logging.getLogger(__name__)

UPLOADS_DIR = Path("data/uploads")
TMP_DIR = UPLOADS_DIR / ".tmp"

_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
# Generous total cap. Real-world 200-300 page reports take ~10-15 min on
# CPU-only BGE; the original 5-min limit cancelled mid-run and surfaced as
# 解析失败. 30 min safely covers any 20 MB PDF we accept upstream.
_INGESTION_TIMEOUT = 1800.0

# Strong refs to in-flight ingestion tasks. asyncio's event loop only holds
# weak references, so a fire-and-forget create_task() can be GC'd mid-run —
# the coroutine vanishes silently, the wait_for timeout never fires, and the
# documents row stays stuck in 'processing' forever. Keep the Task alive by
# adding it to this set and discarding on completion.
_INGESTION_TASKS: set[asyncio.Task] = set()


async def _run_ingestion(
    document_id, *, path: Path, sm: async_sessionmaker, embedder, timeout: float
) -> None:
    """Launch ingestion in a fresh DB session (separate from the request session)."""
    async with sm() as db:
        mem = MemoryService(db)
        await _ingest_with_timeout(
            document_id, path=path, mem=mem, embedder=embedder,
            iter_pages=iter_pages, chunker=chunk, timeout=timeout,
        )


def make_documents_router(*, embedder: BgeEmbedder) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions/{session_id}/documents")
    async def upload_document(
        session_id: UUID,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
    ):
        mem = MemoryService(db)

        # 1) session ownership
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != DEMO_USER_ID:
            raise HTTPException(404, "session not found")

        # validate extension
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, "只支持 .pdf 扩展名")

        # 2) document_id assigned upfront
        document_id = uuid4()

        # 3) write temp
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = TMP_DIR / f"{document_id}.pdf"
        body = await file.read()
        if len(body) > _UPLOAD_MAX_BYTES:
            raise HTTPException(400, "文件超过 20 MB 限制")
        temp_path.write_bytes(body)

        # 4) validate PDF
        try:
            meta = open_pdf_meta(temp_path)
        except PdfValidationError as e:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(400, str(e))

        # 5) INSERT documents row
        try:
            doc = await mem.create_document(
                document_id=document_id,
                user_id=DEMO_USER_ID,
                session_id=session_id,
                filename=file.filename,
                page_count=meta.page_count,
                byte_size=len(body),
            )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "数据库写入失败")

        # 6) atomic rename
        final_path = UPLOADS_DIR / f"{document_id}.pdf"
        try:
            os.replace(temp_path, final_path)
        except Exception:
            await mem.delete_document(document_id)
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "文件落盘失败")

        # 7) launch background ingestion with its own DB session
        task = asyncio.create_task(_run_ingestion(
            document_id, path=final_path, sm=_get_default_sm(), embedder=embedder,
            timeout=_INGESTION_TIMEOUT,
        ))
        _INGESTION_TASKS.add(task)
        task.add_done_callback(_INGESTION_TASKS.discard)

        # 8) return
        return {
            "document_id": str(document_id),
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "page_count": doc.page_count,
        }

    @router.get("/sessions/{session_id}/documents")
    async def list_documents(session_id: UUID, db: AsyncSession = Depends(get_db)):
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != DEMO_USER_ID:
            raise HTTPException(404, "session not found")
        rows = await mem.list_documents(session_id)
        return [
            {
                "document_id": str(d.id),
                "filename": d.filename,
                "page_count": d.page_count,
                "progress_page": d.progress_page,
                "status": d.status.value if hasattr(d.status, "value") else d.status,
                "error_message": d.error_message,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            } for d in rows
        ]

    @router.delete("/sessions/{session_id}/documents/{document_id}", status_code=204)
    async def delete_document(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
    ):
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != DEMO_USER_ID:
            raise HTTPException(404, "session not found")
        doc = await mem.get_document(document_id)
        if doc is None or doc.session_id != session_id:
            raise HTTPException(404, "document not found")
        status = doc.status.value if hasattr(doc.status, "value") else doc.status
        if status == "processing":
            raise HTTPException(
                409, "文档正在解析中，请等待完成或解析超时后再删除"
            )

        await mem.delete_document(document_id)
        try:
            (UPLOADS_DIR / f"{document_id}.pdf").unlink(missing_ok=True)
        except Exception:
            log.warning("failed to unlink %s.pdf", document_id)

    @router.get("/sessions/{session_id}/documents/{document_id}/progress")
    async def progress_stream(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
    ):
        from fastapi.responses import StreamingResponse
        import json

        async def gen():
            mem = MemoryService(db)
            while True:
                # Ingestion writes from a different session, so this session's
                # identity map would otherwise serve a stale Document instance
                # forever. Expire before re-fetching so each poll hits the DB.
                db.expire_all()
                doc = await mem.get_document(document_id)
                if doc is None:
                    yield f"event: done\ndata: {json.dumps({'status':'failed','error':'gone'})}\n\n"
                    return
                status = doc.status.value if hasattr(doc.status, "value") else doc.status
                if status in ("ready", "failed"):
                    yield ("event: done\ndata: " +
                           json.dumps({"status": status, "error": doc.error_message},
                                      ensure_ascii=False) + "\n\n")
                    return
                payload = {
                    "page": doc.progress_page,
                    "total": doc.page_count,
                    "phase": doc.progress_phase or "ingesting",
                }
                yield "event: progress\ndata: " + json.dumps(payload) + "\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
