"""Async data-access layer. Spec §3 + §4 + §5."""
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.schemas import (
    Document, DocumentChunk, DocumentStatus, Message, MessageRole, Session, User,
)

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class MemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- users ----
    async def upsert_demo_user(self) -> User:
        existing = await self.db.get(User, DEMO_USER_ID)
        if existing:
            return existing
        user = User(id=DEMO_USER_ID, name="demo")
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ---- sessions ----
    async def create_session(self, user_id: UUID) -> Session:
        s = Session(id=uuid4(), user_id=user_id)
        self.db.add(s)
        await self.db.commit()
        await self.db.refresh(s)
        return s

    async def list_sessions(self, user_id: UUID, limit: int = 50) -> Sequence[Session]:
        result = await self.db.execute(
            select(Session).where(Session.user_id == user_id)
            .order_by(Session.last_active_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def get_session(self, session_id: UUID) -> Session | None:
        return await self.db.get(Session, session_id)

    # ---- messages ----
    async def list_messages(self, session_id: UUID) -> Sequence[Message]:
        result = await self.db.execute(
            select(Message).where(Message.session_id == session_id)
            .order_by(Message.id)
        )
        return result.scalars().all()

    async def save_user_message(self, session_id: UUID, content: str) -> Message:
        m = Message(session_id=session_id, role=MessageRole.user, content=content)
        self.db.add(m)
        await self.db.commit()
        await self.db.refresh(m)
        return m

    async def save_assistant_message(
        self, session_id: UUID, content: str,
        citations: list | None = None, tool_calls: dict | None = None,
    ) -> Message:
        m = Message(
            session_id=session_id, role=MessageRole.assistant,
            content=content, citations=citations, tool_calls=tool_calls,
        )
        self.db.add(m)
        await self.db.commit()
        await self.db.refresh(m)
        return m

    async def save_tool_message(self, session_id: UUID, tool_call_id: str, content: str) -> Message:
        m = Message(session_id=session_id, role=MessageRole.tool,
                    tool_call_id=tool_call_id, content=content)
        self.db.add(m)
        await self.db.commit()
        await self.db.refresh(m)
        return m

    # ---- documents ----
    async def create_document(
        self, *, user_id: UUID, session_id: UUID,
        filename: str, page_count: int, byte_size: int,
        document_id: UUID | None = None,
    ) -> Document:
        from datetime import datetime, timezone
        doc = Document(
            id=document_id or uuid4(),
            user_id=user_id, session_id=session_id,
            filename=filename, page_count=page_count, byte_size=byte_size,
            status=DocumentStatus.processing, progress_page=0,
            ingestion_started_at=datetime.now(timezone.utc),
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def get_document(self, document_id: UUID) -> Document | None:
        return await self.db.get(Document, document_id)

    async def list_documents(self, session_id: UUID) -> Sequence[Document]:
        result = await self.db.execute(
            select(Document).where(Document.session_id == session_id)
            .order_by(Document.uploaded_at)
        )
        return result.scalars().all()

    async def update_document(self, document_id: UUID, **fields) -> None:
        if not fields:
            return
        await self.db.execute(
            update(Document).where(Document.id == document_id).values(**fields)
        )
        await self.db.commit()

    async def delete_document(self, document_id: UUID) -> None:
        # CASCADE handles document_chunks; messages.citations preserved (JSONB).
        await self.db.execute(delete(Document).where(Document.id == document_id))
        await self.db.commit()

    async def count_documents_by_status(self, session_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(Document.status, func.count())
            .where(Document.session_id == session_id)
            .group_by(Document.status)
        )
        out = {"processing": 0, "ready": 0, "failed": 0}
        for status, n in result.all():
            key = status.value if hasattr(status, "value") else status
            out[key] = n
        return out

    # ---- chunks ----
    async def bulk_insert_chunks(
        self, document_id: UUID, chunks: Iterable[dict]
    ) -> None:
        objs = [
            DocumentChunk(
                document_id=document_id,
                page_no=c["page_no"], chunk_idx=c["chunk_idx"],
                content=c["content"], content_embedding=c["embedding"],
                token_count=c["token_count"],
            ) for c in chunks
        ]
        self.db.add_all(objs)
        await self.db.commit()

    async def delete_chunks_for_document(self, document_id: UUID) -> None:
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self.db.commit()

    async def search_chunks(
        self, session_id: UUID, *, query_embedding: list[float],
        top_k: int, min_similarity: float,
    ) -> list[dict]:
        """Return list of {doc_id, filename, page_no, content, score}.
        Filters by similarity >= min_similarity. Spec §5.
        """
        sql = """
        SELECT dc.document_id, d.filename, dc.page_no, dc.content,
               1 - (dc.content_embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.session_id = :sid AND d.status = 'ready'
        ORDER BY dc.content_embedding <=> CAST(:qvec AS vector)
        LIMIT :top_k
        """
        result = await self.db.execute(
            text(sql),
            {"qvec": str(query_embedding), "sid": str(session_id), "top_k": top_k},
        )
        rows = result.mappings().all()
        return [
            {
                "doc_id": str(r["document_id"]),
                "filename": r["filename"],
                "page_no": r["page_no"],
                "content": r["content"],
                "score": float(r["similarity"]),
            }
            for r in rows
            if float(r["similarity"]) >= min_similarity
        ]


# Keep MessageRecord dataclass for summarizer.py compatibility.
# This may become deprecated in T12 when summarizer is fully wired.
from dataclasses import dataclass, field


@dataclass
class MessageRecord:
    role: str
    content: str
    tool_calls: dict | None = None
