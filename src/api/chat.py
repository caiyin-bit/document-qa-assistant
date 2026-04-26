"""POST /chat and POST /sessions endpoints, with per-request DB session."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)
UPLOADS_DIR = Path("data/uploads")

_TITLE_MAX_CHARS = 24


def _derive_title(first_user_msg: str | None) -> str:
    """Sidebar title: first user message truncated, or '新对话' before any message."""
    if not first_user_msg:
        return "新对话"
    text = first_user_msg.strip().replace("\n", " ")
    if len(text) <= _TITLE_MAX_CHARS:
        return text
    return text[:_TITLE_MAX_CHARS] + "…"

from src.api.sse import SSEStreamingResponse, to_sse_bytes
from src.core.conversation_engine import ConversationEngine
from src.core.memory_service import MemoryService
from src.core.persona_loader import PersonaLoader
from src.core.tool_registry import ToolRegistry


class ChatRequest(BaseModel):
    session_id: UUID
    message: str


class SessionCreatedResponse(BaseModel):
    session_id: UUID


class SessionListItem(BaseModel):
    session_id: UUID
    created_at: datetime
    title: str


class HistoricalMessage(BaseModel):
    role: str
    content: str | None
    tool_calls: list[dict] | None = None
    # Persisted citations (DB column messages.citations JSONB) so the
    # citation card + clickable PDF chips survive a page refresh. Each
    # element is the same dict the SSE `citations` event emits.
    citations: list[dict] | None = None


@dataclass(frozen=True)
class ConvSettings:
    max_tool_iterations: int
    compress_trigger_threshold: int   # replaces session_history_limit
    compress_keep_recent: int         # new
    retrieve_top_k: int
    similarity_threshold: float


@dataclass
class ChatDependencies:
    """Process-wide singletons. The DB session is per-request, not here."""

    sessionmaker: async_sessionmaker[AsyncSession]
    persona: PersonaLoader
    embedder: object  # duck-typed: must expose .embed(text) -> list[float]
    llm: object       # duck-typed: must expose async chat(messages, tools=...)
    default_user_id: UUID
    settings: ConvSettings
    min_similarity: float = 0.35
    top_k: int = 16
    reranker: object | None = None  # exposes .score_pairs_async(query, passages)
    rerank_top_n: int = 5


def make_router(deps: ChatDependencies) -> APIRouter:
    router = APIRouter()

    async def get_db() -> AsyncIterator[AsyncSession]:
        async with deps.sessionmaker() as session:
            yield session

    def _build_memory(db: AsyncSession) -> MemoryService:
        return MemoryService(db)

    def _build_engine(db: AsyncSession) -> ConversationEngine:
        mem = _build_memory(db)
        tools = ToolRegistry(
            mem=mem,
            embedder=deps.embedder,
            min_similarity=deps.min_similarity,
            top_k=deps.top_k,
            reranker=deps.reranker,
            rerank_top_n=deps.rerank_top_n,
        )
        return ConversationEngine(
            mem=mem,
            llm=deps.llm,
            tools=tools,
            persona=deps.persona.load(),
            max_tool_iterations=deps.settings.max_tool_iterations,
        )

    @router.post("/sessions", response_model=SessionCreatedResponse)
    async def create_session(
        db: AsyncSession = Depends(get_db),
    ) -> SessionCreatedResponse:
        memory = _build_memory(db)
        await memory.upsert_demo_user()
        sess = await memory.create_session(user_id=deps.default_user_id)
        return SessionCreatedResponse(session_id=sess.id)

    @router.get("/sessions", response_model=list[SessionListItem])
    async def list_sessions(
        limit: int = 50, db: AsyncSession = Depends(get_db)
    ) -> list[SessionListItem]:
        if limit < 1 or limit > 200:
            raise HTTPException(
                status_code=400,
                detail="limit must be between 1 and 200",
            )
        memory = _build_memory(db)
        rows = await memory.list_sessions_with_titles(
            user_id=deps.default_user_id, limit=limit
        )
        return [
            SessionListItem(
                session_id=sess.id,
                created_at=sess.created_at,
                title=_derive_title(first_msg),
            )
            for sess, first_msg in rows
        ]

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: UUID, db: AsyncSession = Depends(get_db)
    ):
        memory = _build_memory(db)
        sess = await memory.get_session(session_id)
        if sess is None or sess.user_id != deps.default_user_id:
            raise HTTPException(
                status_code=404,
                detail="session not found or not owned by current user",
            )
        # Refuse if any doc is still ingesting — otherwise cascade delete
        # would remove the documents row out from under the running ingestion
        # task and crash it on FK violation. Mirrors delete_document's guard.
        counts = await memory.count_documents_by_status(session_id)
        if counts.get("processing", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="会话内有文档正在解析中，请等待完成或解析超时（≤5 分钟）后再删除",
            )
        doc_ids = await memory.delete_session(session_id)
        for did in doc_ids:
            try:
                (UPLOADS_DIR / f"{did}.pdf").unlink(missing_ok=True)
            except Exception:
                log.warning("failed to unlink %s.pdf during session delete", did)

    @router.get(
        "/sessions/{session_id}/messages",
        response_model=list[HistoricalMessage],
    )
    async def list_messages(
        session_id: UUID, db: AsyncSession = Depends(get_db)
    ) -> list[HistoricalMessage]:
        memory = _build_memory(db)
        sess = await memory.get_session(session_id)
        if sess is None or sess.user_id != deps.default_user_id:
            raise HTTPException(
                status_code=404,
                detail="session not found or not owned by current user",
            )
        rows = await memory.list_messages(session_id)
        out: list[HistoricalMessage] = []
        for m in rows:
            if m.role == "tool":
                continue
            out.append(HistoricalMessage(
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                citations=m.citations,
            ))
        return out

    @router.post("/chat/stream")
    async def chat_stream(
        req: ChatRequest, db: AsyncSession = Depends(get_db)
    ) -> SSEStreamingResponse:
        # Validate session up-front so a stale frontend session_id (e.g.
        # leftover in URL after a session was deleted or DB truncated)
        # produces a 404, not an FK violation deep inside the SSE stream.
        memory = _build_memory(db)
        sess = await memory.get_session(req.session_id)
        if sess is None or sess.user_id != deps.default_user_id:
            raise HTTPException(
                status_code=404,
                detail="session not found or not owned by current user",
            )
        engine = _build_engine(db)
        events = engine.handle_stream(
            session_id=req.session_id,
            message=req.message,
        )
        return SSEStreamingResponse(
            to_sse_bytes(events),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return router
