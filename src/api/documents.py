"""Documents API. Spec §4 (upload + temp/atomic rename + cleanup invariants)."""
import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_user
from src.core.memory_service import MemoryService
from src.db.session import get_db
from src.embedding.bge_embedder import BgeEmbedder
from src.ingest.pdf_parser import open_pdf_meta, PdfValidationError

log = logging.getLogger(__name__)

UPLOADS_DIR = Path("data/uploads")
TMP_DIR = UPLOADS_DIR / ".tmp"

_UPLOAD_MAX_BYTES = 20 * 1024 * 1024


def make_documents_router(*, embedder: BgeEmbedder, llm=None) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions/{session_id}/documents")
    async def upload_document(
        session_id: UUID,
        request: Request,
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        mem = MemoryService(db)

        # 1) session ownership
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
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
                user_id=user_id,
                session_id=session_id,
                filename=file.filename,
                page_count=meta.page_count,
                byte_size=len(body),
            )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "数据库写入失败")

        # 6) atomic rename — must happen BEFORE enqueue so the worker
        # sees the file when it picks the job up
        final_path = UPLOADS_DIR / f"{document_id}.pdf"
        try:
            os.replace(temp_path, final_path)
        except Exception:
            await mem.delete_document(document_id)
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "文件落盘失败")

        # 7) enqueue ingestion via arq with deterministic _job_id (dedup
        # with the startup reaper). On Redis failure, roll back disk + db.
        try:
            job = await request.app.state.arq_pool.enqueue_job(
                "ingest_document", str(document_id),
                _job_id=f"ingest:{document_id}",
            )
            result = "queued" if job is not None else "deduped"
        except RedisError as e:
            log.error("event=ingest.enqueue doc_id=%s job_id=ingest:%s result=redis_error err=%s",
                       document_id, document_id, e)
            try:
                await mem.delete_document(document_id)
            except Exception:
                pass
            final_path.unlink(missing_ok=True)
            raise HTTPException(503, "任务队列不可达，请稍后重试")
        log.info("event=ingest.enqueue doc_id=%s job_id=ingest:%s result=%s",
                  document_id, document_id, result)

        # 8) return
        return {
            "document_id": str(document_id),
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "page_count": doc.page_count,
        }

    @router.get("/sessions/{session_id}/documents")
    async def list_documents(
        session_id: UUID, db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
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

    @router.get("/sessions/{session_id}/documents/library")
    async def list_user_library(
        session_id: UUID, db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        """Lists user's other ready docs not yet attached to this session.
        Powers the "+ 添加已有文档" dropdown so a brand-new conversation
        can pull in PDFs uploaded earlier."""
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
            raise HTTPException(404, "session not found")
        rows = await mem.list_user_library(
            user_id, exclude_session_id=session_id,
        )
        return [
            {
                "document_id": str(d.id),
                "filename": d.filename,
                "page_count": d.page_count,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            } for d in rows
        ]

    class AttachBody(BaseModel):
        document_ids: list[UUID]

    @router.post("/sessions/{session_id}/documents/attach", status_code=204)
    async def attach_documents(
        session_id: UUID, body: AttachBody,
        db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        """Attach existing user-owned documents to this session via the
        session_documents M2M link. Idempotent (ON CONFLICT DO NOTHING)."""
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
            raise HTTPException(404, "session not found")
        for did in body.document_ids:
            doc = await mem.get_document(did)
            # Defensive ownership check: don't let a session attach docs
            # that belong to another user.
            if doc is None or doc.user_id != user_id:
                continue
            await mem.attach_document_to_session(session_id, did)

    @router.delete("/sessions/{session_id}/documents/{document_id}", status_code=204)
    async def delete_document(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        """Detach the doc from this session. Only fully deletes (and
        unlinks the PDF on disk) if no OTHER session still references
        it via session_documents — otherwise the doc stays alive in
        the user's library."""
        from sqlalchemy import text as _text
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
            raise HTTPException(404, "session not found")
        doc = await mem.get_document(document_id)
        if doc is None or doc.user_id != user_id:
            raise HTTPException(404, "document not found")
        status = doc.status.value if hasattr(doc.status, "value") else doc.status
        if status == "processing":
            raise HTTPException(
                409, "文档正在解析中，请等待完成或解析超时后再删除"
            )

        await mem.detach_document_from_session(session_id, document_id)
        # Garbage-collect: if no sessions still reference this doc, fully
        # delete (cascades chunks) and unlink the PDF from disk.
        result = await db.execute(
            _text(
                "SELECT COUNT(*) FROM session_documents "
                "WHERE document_id = :did"
            ),
            {"did": str(document_id)},
        )
        remaining = result.scalar() or 0
        if remaining == 0:
            await mem.delete_document(document_id)
            try:
                (UPLOADS_DIR / f"{document_id}.pdf").unlink(missing_ok=True)
            except Exception:
                log.warning("failed to unlink %s.pdf", document_id)

    @router.get("/sessions/{session_id}/documents/{document_id}/intro")
    async def get_document_intro(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        """LLM-generated 2-3 sentence summary + 3 suggested follow-up
        questions for the document. Used by the empty-state of the chat
        pane to give the user a starting point. Fetches the first ~12
        chunks (head of doc — usually exec summary / TOC area) so the
        prompt stays compact.

        No DB cache yet — each call hits the LLM. Frontend caches the
        result in localStorage keyed by document_id so re-renders don't
        re-bill.
        """
        if llm is None:
            raise HTTPException(503, "LLM 未配置")
        from sqlalchemy import text
        import json
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
            raise HTTPException(404, "session not found")
        doc = await mem.get_document(document_id)
        if doc is None or doc.user_id != user_id:
            raise HTTPException(404, "document not found")
        status = doc.status.value if hasattr(doc.status, "value") else doc.status
        if status != "ready":
            raise HTTPException(409, "文档尚未解析完成")
        result = await db.execute(
            text(
                "SELECT content FROM document_chunks "
                "WHERE document_id = :did "
                "ORDER BY page_no, chunk_idx LIMIT 12"
            ),
            {"did": str(document_id)},
        )
        head_text = "\n\n".join(r[0] for r in result.all())[:6000]
        prompt = (
            "下面是一份 PDF 文档开头部分的摘录。请用 2-3 句话概括这份文档"
            "讲什么（不要重复文件名），然后给出 3 个最有意义的"
            "follow-up 问题。严格按 JSON 输出，键名为 summary 和 questions。\n\n"
            f"{head_text}\n\n"
            '只输出 JSON：{"summary":"…","questions":["…","…","…"]}'
        )
        try:
            resp = await llm.chat(
                messages=[{"role": "user", "content": prompt}], tools=[],
            )
            body = (resp.content or "").strip()
            # tolerate ```json fences
            if body.startswith("```"):
                body = body.strip("`").lstrip("json").strip()
            data = json.loads(body)
            return {
                "summary": str(data.get("summary", "")),
                "questions": [str(q) for q in (data.get("questions") or [])][:3],
            }
        except Exception as e:
            log.warning("intro generation failed for %s: %s", document_id, e)
            raise HTTPException(502, "摘要生成失败，请稍后再试")

    @router.get("/sessions/{session_id}/documents/{document_id}/file")
    async def get_document_file(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ):
        """Serve the original PDF inline so the browser can render it (for
        the citation-jump preview pane). Validates session ownership +
        document scope so one user can't fetch another's uploads."""
        from fastapi.responses import FileResponse
        mem = MemoryService(db)
        sess = await mem.get_session(session_id)
        if sess is None or sess.user_id != user_id:
            raise HTTPException(404, "session not found")
        doc = await mem.get_document(document_id)
        if doc is None or doc.user_id != user_id:
            raise HTTPException(404, "document not found")
        path = UPLOADS_DIR / f"{document_id}.pdf"
        if not path.exists():
            raise HTTPException(404, "file missing on disk")
        # HTTP headers must be Latin-1; non-ASCII filenames need RFC 5987
        # encoding (percent-encoded UTF-8 in `filename*`). The plain
        # `filename=` fallback is left as the document_id.pdf so older
        # clients still get a sensible name.
        from urllib.parse import quote
        encoded = quote(doc.filename, safe="")
        cd = (
            f'inline; filename="{document_id}.pdf"; '
            f"filename*=UTF-8''{encoded}"
        )
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={"Content-Disposition": cd},
        )

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
