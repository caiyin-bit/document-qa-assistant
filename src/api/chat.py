"""POST /chat and POST /sessions endpoints, with per-request DB session."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.api.sse import SSEStreamingResponse, to_sse_bytes
from src.core.conversation_engine import ConversationEngine
from src.core.memory_service import MemoryService
from src.core.persona_loader import PersonaLoader
from src.core.tool_registry import ToolRegistry


class ChatRequest(BaseModel):
    session_id: UUID
    message: str


class ChatResponse(BaseModel):
    content: str


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
    summarizer: object  # duck-typed: must expose async summarize(prior, msgs)
    default_user_id: UUID
    settings: ConvSettings
    min_similarity: float = 0.35
    top_k: int = 16


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
        )
        return ConversationEngine(
            mem=mem,
            llm=deps.llm,
            tools=tools,
            persona=deps.persona,
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
        rows = await memory.list_recent_sessions(
            user_id=deps.default_user_id, limit=limit
        )
        return [
            SessionListItem(
                session_id=r.id, created_at=r.created_at, title=r.title
            )
            for r in rows
        ]

    @router.get(
        "/sessions/{session_id}/messages",
        response_model=list[HistoricalMessage],
    )
    async def list_messages(
        session_id: UUID, db: AsyncSession = Depends(get_db)
    ) -> list[HistoricalMessage]:
        memory = _build_memory(db)
        rows = await memory.list_all_messages(
            session_id=session_id, user_id=deps.default_user_id
        )
        if rows is None:
            raise HTTPException(
                status_code=404,
                detail="session not found or not owned by current user",
            )
        out: list[HistoricalMessage] = []
        for m in rows:
            if m.role == "tool":
                continue
            out.append(HistoricalMessage(
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
            ))
        return out

    @router.post("/chat", response_model=ChatResponse)
    async def chat(
        req: ChatRequest, db: AsyncSession = Depends(get_db)
    ) -> ChatResponse:
        engine = _build_engine(db)
        reply = await engine.handle(
            user_id=deps.default_user_id,
            session_id=req.session_id,
            user_message=req.message,
        )
        return ChatResponse(content=reply)

    @router.post("/chat/stream")
    async def chat_stream(
        req: ChatRequest, db: AsyncSession = Depends(get_db)
    ) -> SSEStreamingResponse:
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
