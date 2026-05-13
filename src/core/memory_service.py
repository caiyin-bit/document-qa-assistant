"""Async data-access layer. Spec §3 + §4 + §5."""
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.schemas import (
    Document, DocumentChunk, DocumentStatus, Message, MessageRole,
    Session, SessionDocument, User,
)

from collections import defaultdict


def _rrf_fuse_scores(
    stages: list[list[dict]], *, key: str = "chunk_id", k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion across N rank-ordered stages.

    Each stage is a list of dict-like hits keyed by `key` (default
    "chunk_id"). Within one stage, the same id at multiple ranks
    contributes only its best (lowest) rank — RRF semantic: each
    stage votes at most once per item.

    Caller must sort the returned scores with an explicit tiebreak,
    e.g. `sorted(scores, key=lambda cid: (-scores[cid], cid))`. The
    dict insertion order is NOT a stable tiebreak across runs.
    """
    scores: dict[str, float] = defaultdict(float)
    for stage in stages:
        seen_in_stage: set[str] = set()
        for rank, row in enumerate(stage, start=1):
            row_id = row[key]
            if row_id in seen_in_stage:
                continue
            seen_in_stage.add(row_id)
            scores[row_id] += 1.0 / (k + rank)
    return dict(scores)


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

    async def list_sessions_with_titles(
        self, user_id: UUID, limit: int = 50,
    ) -> list[tuple[Session, str | None]]:
        """Return (session, first_user_message_content) for each session.
        Single round-trip via correlated subquery — used to render meaningful
        sidebar titles without a dedicated `title` column on sessions."""
        sql = text(
            """
            SELECT s.id AS sid, s.created_at, s.last_active_at,
                   s.summary, s.summary_until_message_id, s.user_id,
                   (SELECT m.content FROM messages m
                    WHERE m.session_id = s.id AND m.role = 'user'
                    ORDER BY m.id LIMIT 1) AS first_user_msg
            FROM sessions s
            WHERE s.user_id = :uid
            ORDER BY s.last_active_at DESC
            LIMIT :lim
            """
        )
        result = await self.db.execute(sql, {"uid": str(user_id), "lim": limit})
        rows = result.mappings().all()
        out: list[tuple[Session, str | None]] = []
        for r in rows:
            sess = Session(
                id=r["sid"],
                user_id=r["user_id"],
                created_at=r["created_at"],
                last_active_at=r["last_active_at"],
                summary=r["summary"],
                summary_until_message_id=r["summary_until_message_id"],
            )
            out.append((sess, r["first_user_msg"]))
        return out

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
        # Auto-attach to the creating session via the M2M link, so listing
        # / retrieval through session_documents finds it. The link table
        # is the source of truth for visibility.
        self.db.add(SessionDocument(session_id=session_id, document_id=doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def get_document(self, document_id: UUID) -> Document | None:
        return await self.db.get(Document, document_id)

    async def list_documents(self, session_id: UUID) -> Sequence[Document]:
        """Documents visible in this session — goes through the
        session_documents M2M link, NOT documents.session_id directly,
        so docs attached from other sessions show up here too."""
        result = await self.db.execute(
            select(Document)
            .join(SessionDocument, SessionDocument.document_id == Document.id)
            .where(SessionDocument.session_id == session_id)
            .order_by(Document.uploaded_at)
        )
        return result.scalars().all()

    async def list_user_library(
        self, user_id: UUID, *, exclude_session_id: UUID | None = None,
    ) -> Sequence[Document]:
        """All docs owned by `user_id`, optionally filtered to those NOT
        already attached to `exclude_session_id`. Used by the "import
        existing document" picker so the dropdown only shows docs the
        current session doesn't already have."""
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.ready)
            .order_by(Document.uploaded_at.desc())
        )
        if exclude_session_id is not None:
            attached = (
                select(SessionDocument.document_id)
                .where(SessionDocument.session_id == exclude_session_id)
            )
            stmt = stmt.where(Document.id.notin_(attached))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def attach_document_to_session(
        self, session_id: UUID, document_id: UUID,
    ) -> None:
        """Idempotent — ON CONFLICT DO NOTHING via PK uniqueness."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = (
            pg_insert(SessionDocument)
            .values(session_id=session_id, document_id=document_id)
            .on_conflict_do_nothing(index_elements=["session_id", "document_id"])
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def detach_document_from_session(
        self, session_id: UUID, document_id: UUID,
    ) -> None:
        await self.db.execute(
            delete(SessionDocument).where(
                (SessionDocument.session_id == session_id) &
                (SessionDocument.document_id == document_id),
            )
        )
        await self.db.commit()

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

    async def delete_session(self, session_id: UUID) -> list[UUID]:
        """Cascade delete a session. Documents are SHARED (M2M via
        session_documents) so we only delete docs that would be orphaned
        — i.e. docs only attached to this session. Returns the deleted
        document IDs so the API layer can unlink their PDFs from disk.
        """
        # Orphan = attached to this session AND no other session.
        orphan_rows = await self.db.execute(text("""
            SELECT document_id FROM session_documents
            WHERE session_id = :sid
            AND document_id NOT IN (
                SELECT document_id FROM session_documents
                WHERE session_id <> :sid
            )
        """), {"sid": str(session_id)})
        doc_ids: list[UUID] = [r[0] for r in orphan_rows.all()]
        await self.db.execute(
            delete(Message).where(Message.session_id == session_id)
        )
        if doc_ids:
            # Cascades to document_chunks + session_documents links.
            await self.db.execute(
                delete(Document).where(Document.id.in_(doc_ids))
            )
        # Session delete cascades any remaining session_documents links
        # (i.e. shared docs stay alive in their other sessions).
        await self.db.execute(
            delete(Session).where(Session.id == session_id)
        )
        await self.db.commit()
        return doc_ids

    async def count_documents_by_status(self, session_id: UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(Document.status, func.count())
            .join(SessionDocument, SessionDocument.document_id == Document.id)
            .where(SessionDocument.session_id == session_id)
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
        """Return list of {chunk_id, doc_id, filename, page_no, content, score}.
        Vector cosine recall, filtered by similarity >= min_similarity. Spec §5.
        """
        # ivfflat default probes=1 only scans 1 of the 100 lists in our
        # index — for many queries the matching chunks live in other lists
        # and silently get 0 hits. probes≈sqrt(lists)=10 is the standard
        # accuracy/latency tradeoff. Without this, recall is very poor.
        await self.db.execute(text("SET LOCAL ivfflat.probes = 10"))
        # Visibility is via session_documents M2M, not documents.session_id
        # (docs can be attached to multiple sessions). The JOIN is the only
        # change vs. the original; index ix_session_documents_session_id
        # makes it cheap.
        sql = """
        SELECT dc.id, dc.document_id, d.filename, dc.page_no, dc.content,
               1 - (dc.content_embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        JOIN session_documents sd ON sd.document_id = d.id
        WHERE sd.session_id = :sid AND d.status = 'ready'
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
                "chunk_id": str(r["id"]),
                "doc_id": str(r["document_id"]),
                "filename": r["filename"],
                "page_no": r["page_no"],
                "content": r["content"],
                "score": float(r["similarity"]),
            }
            for r in rows
            if float(r["similarity"]) >= min_similarity
        ]

    async def search_chunks_keyword(
        self, session_id: UUID, *, query: str, top_k: int,
    ) -> list[dict]:
        """Lexical recall via pg_trgm character-trigram similarity.

        Complements vector cosine: exact-substring matches (numbers, proper
        nouns, OOV terms) that embeddings smear are recovered here. The
        `%` operator uses the GIN index from migration 0002 to keep this
        fast on large tables.
        """
        # Cast :q to text explicitly — asyncpg passes string params with
        # type 'unknown' otherwise, and Postgres can't resolve
        # similarity(text, unknown) → 42883 UndefinedFunction.
        #
        # We don't use `dc.content % :q` (pg_trgm's % operator) because
        # its default threshold (0.3) is too high for short Chinese
        # queries against long chunks. Instead order by similarity DESC
        # with a `> 0` floor — keeps zero-overlap chunks (e.g. ASCII
        # query against pure-CJK corpus) out of the result set.
        # Same visibility model as search_chunks — JOIN session_documents.
        sql = """
        SELECT dc.id, dc.document_id, d.filename, dc.page_no, dc.content,
               similarity(dc.content, CAST(:q AS text)) AS score
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        JOIN session_documents sd ON sd.document_id = d.id
        WHERE sd.session_id = :sid AND d.status = 'ready'
          AND similarity(dc.content, CAST(:q AS text)) > 0
        ORDER BY similarity(dc.content, CAST(:q AS text)) DESC
        LIMIT :top_k
        """
        result = await self.db.execute(
            text(sql),
            {"q": query, "sid": str(session_id), "top_k": top_k},
        )
        rows = result.mappings().all()
        return [
            {
                "chunk_id": str(r["id"]),
                "doc_id": str(r["document_id"]),
                "filename": r["filename"],
                "page_no": r["page_no"],
                "content": r["content"],
                "score": float(r["score"]),
            }
            for r in rows
        ]

    async def search_chunks_hybrid(
        self, session_id: UUID, *, query: str, query_embedding: list[float],
        top_k: int, min_similarity: float, rrf_k: int = 60,
    ) -> list[dict]:
        """Hybrid vector + trigram recall fused via Reciprocal Rank Fusion.

        Uses the generalized `_rrf_fuse_scores` helper so additional recall
        stages (e.g. BM25, second-pass rerank) can be added without
        rewriting the fusion logic. Explicit tiebreak by chunk_id keeps
        ordering deterministic across runs.

        Stages run sequentially, not in parallel: both queries share
        `self.db` (one AsyncSession) and SQLAlchemy raises on concurrent
        operations against the same session. Cost is ~10ms — both are
        GIN-index lookups.
        """
        vec_hits = await self.search_chunks(
            session_id, query_embedding=query_embedding,
            top_k=top_k, min_similarity=min_similarity,
        )
        kw_hits = await self.search_chunks_keyword(
            session_id, query=query, top_k=top_k,
        )

        fused_scores = _rrf_fuse_scores([vec_hits, kw_hits], k=rrf_k)

        # First-occurrence wins for the hit payload; fields like content/snippet
        # are the same across stages for a given chunk_id (same row in DB).
        by_id: dict[str, dict] = {}
        for hit in (*vec_hits, *kw_hits):
            if hit["chunk_id"] not in by_id:
                by_id[hit["chunk_id"]] = hit

        # Explicit tiebreak: (score DESC, chunk_id ASC). Without this, ties
        # resolve via dict insertion order, which is consistent within one
        # process but masks real coverage bugs in the eval harness.
        fused_ids = sorted(
            fused_scores, key=lambda cid: (-fused_scores[cid], cid),
        )[:top_k]

        out = []
        for cid in fused_ids:
            row = dict(by_id[cid])
            row["score"] = fused_scores[cid]
            out.append(row)
        return out
