# Document QA Assistant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Chinese-language PDF document QA chatbot that answers strictly from uploaded content with page-level citations, deployable via `docker compose up`.

**Architecture:** FastAPI backend + Next.js frontend. PostgreSQL with pgvector for semantic search using BGE-large-zh-v1.5 embeddings. Moonshot K2.6 LLM via OpenAI-compatible API. Single tool (`search_documents`) constrains LLM to retrieve-then-answer. SSE for both chat streaming and upload progress.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16 + pgvector, pdfplumber, sentence-transformers (BGE), openai SDK; Next.js 15, React 19, Tailwind 4, shadcn/ui, Vitest; pytest + testcontainers; uv + pnpm; docker-compose.

**Spec reference:** `docs/superpowers/specs/2026-04-25-doc-qa-design.md` (canonical source of truth — re-read before each task).

**Source for scaffold:** `/Users/jeff/Work/workspace/chat/` — copy the listed files in Task 0, then never reference again.

---

## File Structure

### Backend (`src/`)

| File | Purpose |
|---|---|
| `main.py` | FastAPI factory, dependency injection, startup hook |
| `config.py` | YAML + env config loading; `MIN_SIMILARITY` env override |
| `api/chat.py` | `POST /sessions`, `GET /sessions`, `GET /sessions/{sid}/messages`, `POST /chat`, `POST /chat/stream` |
| `api/documents.py` | NEW: `POST/GET/DELETE /sessions/{sid}/documents`, `GET .../{did}/progress` |
| `api/sse.py` | StreamEvent, encode_sse, SSEStreamingResponse |
| `core/conversation_engine.py` | handle_stream + 4-template dispatch + structured citations binding |
| `core/tool_registry.py` | Only registers `search_documents` |
| `core/prompt_templates.py` | Templates A / B-EMPTY / B-PROCESSING / B-FAILED |
| `core/persona_loader.py` | Loads `persona/IDENTITY.md` + `persona/SOUL.md` |
| `core/memory_service.py` | NEW from scratch: sessions/messages/documents/chunks CRUD + search |
| `core/summarizer.py` | (kept from scaffold, unused in V1) |
| `llm/kimi_client.py` | (kept from scaffold) |
| `embedding/bge_embedder.py` | (kept from scaffold) |
| `ingest/pdf_parser.py` | NEW: pdfplumber wrapper (open + page_count + per-page text) |
| `ingest/chunker.py` | NEW: paragraph-aware chunker + `_split_oversized` |
| `ingest/ingestion.py` | NEW: `_ingest_document`, `_ingest_with_timeout`, `_mark_failed_and_clean`, `cleanup_stale_documents` |
| `tools/search_documents.py` | NEW: vector search with `MIN_SIMILARITY` filter |
| `db/session.py` | Async engine + sessionmaker |
| `db/migrations/versions/*` | Single new init migration (5 tables + pgvector + ivfflat) |
| `models/schemas.py` | NEW from scratch: User, Session, Message, Document, DocumentChunk |

### Frontend (`frontend/`)

| File | Purpose |
|---|---|
| `app/page.tsx`, `app/layout.tsx` | (kept from scaffold) |
| `components/home.tsx` | (kept; minor: pass document state) |
| `components/sessions-sidebar.tsx` | (kept) |
| `components/chat-pane.tsx` | Major rewrite: D-layout, conditional empty/with-docs |
| `components/message-bubble.tsx` | Add `<CitationCard>` at bottom of assistant bubbles |
| `components/document-upload-hero.tsx` | NEW: empty-state hero with drag-and-drop |
| `components/document-top-bar.tsx` | NEW: top horizontal bar with documents + upload button |
| `components/document-row.tsx` | NEW: 3-state row (processing/ready/failed) with delete button |
| `components/citation-card.tsx` | NEW: red PDF badge + filename + page badge + 2-line snippet |
| `lib/api.ts` | Add `uploadDocument`, `listDocuments`, `deleteDocument` |
| `lib/sse-stream.ts` | Add `citations` ServerEvent variant |
| `lib/use-chat-stream.ts` | Handle `citations` event; bind to assistant message |
| `lib/use-documents.ts` | NEW: list documents + poll until all ready |
| `lib/use-document-progress.ts` | NEW: SSE subscribe per processing document |
| `lib/types.ts` | Add `Document`, `Citation`, extend `Message` |
| `lib/tool-labels.ts` | Replace contents with `{search_documents: '检索文档'}` |

### Other

| Path | Purpose |
|---|---|
| `persona/IDENTITY.md` | NEW: document QA assistant identity |
| `persona/SOUL.md` | NEW: cite-everything, plain-text, no-fabrication |
| `scripts/calibrate_threshold.py` | NEW: threshold calibration (stdout report) |
| `scripts/bootstrap.sh` | (kept; ensure data/uploads dirs created) |
| `tests/unit/test_*.py` | Per spec §10 test list |
| `tests/e2e/test_doc_qa.py` | NEW E2E using Tencent annual report |
| `tests/fixtures/sample_zh.pdf` | NEW: small Chinese PDF for unit tests (built by fixture script) |
| `data/uploads/` | runtime: uploaded PDFs (gitignored, docker volume) |
| `data/uploads/.tmp/` | runtime: temp upload staging |
| `docker-compose.yml` | (kept; add `data/uploads:/app/data/uploads` volume) |
| `Dockerfile`, `frontend/Dockerfile` | (kept) |
| `pyproject.toml` | Add `pdfplumber` dependency |
| `config.yaml` | Add `retrieval.min_similarity: 0.35`, `retrieval.top_k: 16`, `retrieval.top_n: 8` |
| `.env.example` | Add `MIN_SIMILARITY` (commented out, optional) |
| `README.md` | NEW per spec §12 |

---

## Conventions

- **TDD throughout**: failing test first, then minimal impl, then verify pass, then commit.
- **Commit per task** unless task explicitly says split.
- **Never use `--no-verify`**; if a hook fails, fix the underlying issue.
- **Spec is canonical**: when in doubt, re-read the spec section referenced in the task.
- **Test paths use `pytest tests/unit/test_xxx.py::test_yyy -v`** for individual runs.
- **Frontend tests use `cd frontend && pnpm vitest run path/to/test.ts`**.
- **All Chinese fixed responses must match exactly** — copy from spec §1 (the standard-phrasing table).

---

## Task 0: Repo Scaffold (copy + cleanup)

**Goal:** Get a clean scaffold from `/Users/jeff/Work/workspace/chat/` with all insurance-domain code removed. End state: project boots, postgres connects, no tests yet for new features.

**Files:** Many — see commands below.

- [ ] **Step 1: Copy the scaffold tree**

```bash
SRC=/Users/jeff/Work/workspace/chat
DST=/Users/jeff/Work/workspace/document-qa-assistant
cd "$DST"

# Top-level project files
cp "$SRC"/{pyproject.toml,uv.lock,alembic.ini,docker-compose.yml,Dockerfile,config.yaml,.env.example} .
cp -r "$SRC"/scripts .

# Backend src tree (selective)
mkdir -p src/api src/core src/db/migrations/versions src/embedding src/llm src/models src/ingest src/tools
cp "$SRC"/src/__init__.py src/
cp "$SRC"/src/main.py src/
cp "$SRC"/src/config.py src/
cp "$SRC"/src/api/__init__.py "$SRC"/src/api/chat.py "$SRC"/src/api/sse.py src/api/
cp "$SRC"/src/core/__init__.py src/core/
cp "$SRC"/src/core/conversation_engine.py src/core/
cp "$SRC"/src/core/tool_registry.py src/core/
cp "$SRC"/src/core/persona_loader.py src/core/
cp "$SRC"/src/core/prompt_templates.py src/core/
cp "$SRC"/src/core/summarizer.py src/core/
cp "$SRC"/src/embedding/* src/embedding/
cp "$SRC"/src/llm/* src/llm/
cp "$SRC"/src/db/__init__.py "$SRC"/src/db/session.py src/db/

# Frontend tree (selective)
mkdir -p frontend
cp -r "$SRC"/frontend/{app,components,lib,public,Dockerfile,next.config.mjs,package.json,pnpm-lock.yaml,postcss.config.mjs,tailwind.config.ts,tsconfig.json,vitest.config.ts} frontend/
# Remove insurance-specific frontend files (will rewrite)
rm -f frontend/components/tool-chip.tsx
rm -f frontend/lib/tool-labels.ts

# Tests scaffold (keep generic, drop insurance)
mkdir -p tests/unit tests/e2e tests/fixtures
cp "$SRC"/tests/conftest.py tests/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_kimi_client.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_kimi_client_stream.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_bge_embedder.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_db_smoke.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_config.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_persona_loader.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_sse.py tests/unit/ 2>/dev/null || true
cp "$SRC"/tests/unit/test_sse_response_cleanup.py tests/unit/ 2>/dev/null || true
```

- [ ] **Step 2: Stub files that will be fully rewritten in later tasks**

```bash
cd /Users/jeff/Work/workspace/document-qa-assistant

# Empty placeholders so Task 0 ends with a runnable (if minimal) project
mkdir -p src/ingest src/tools persona
: > src/ingest/__init__.py
: > src/tools/__init__.py
echo "# Stub — replaced in Task 1" > src/models/__init__.py
echo "# Stub — replaced in Task 1" > src/models/schemas.py
echo "# Stub — replaced in Task 4" > src/core/memory_service.py
echo "# Stub — replaced in Task 22" > persona/IDENTITY.md
echo "# Stub — replaced in Task 22" > persona/SOUL.md

# Remove insurance-domain alembic migrations (will create one new in Task 1)
rm -rf src/db/migrations/versions/*
touch src/db/migrations/versions/.gitkeep
```

- [ ] **Step 3: Add pdfplumber to pyproject.toml**

Edit `pyproject.toml`. Find the `[project] dependencies = [...]` array and add:
```toml
"pdfplumber>=0.11.0",
```

- [ ] **Step 4: Add config + .env entries**

Edit `config.yaml`, append at the end:
```yaml
retrieval:
  min_similarity: 0.35   # cosine; T2.5 to calibrate
  top_k: 16              # initial pool before threshold filter
  top_n: 8               # returned to LLM
  oversize_max_tokens: 500
  overlap_tokens: 80
ingestion:
  upload_max_bytes: 20971520   # 20 MB
  ingestion_timeout_seconds: 300
```

Edit `.env.example`, append:
```
# Optional: override retrieval threshold (default 0.35)
# MIN_SIMILARITY=0.35
```

- [ ] **Step 5: Verify the project still imports and tests run**

```bash
uv sync
uv run pytest tests/unit -q --ignore=tests/unit/test_db_smoke.py
```

Expected: kept tests pass; ignore db_smoke (no migrations yet).

- [ ] **Step 6: .gitignore the data dir**

Append to `.gitignore` if not already present:
```
data/uploads/
data/uploads/.tmp/
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold (fastapi + pgvector + bge + moonshot + nextjs)"
```

---

## Task 1: Models + Alembic Init Migration

**Goal:** Define the 5 ORM models per spec §3, create one alembic migration that builds them all + pgvector + ivfflat index.

**Files:**
- Create: `src/models/schemas.py` (replace stub)
- Create: `src/db/migrations/versions/0001_init.py`
- Test: `tests/unit/test_models.py`, `tests/unit/test_db_smoke.py` (rewrite)

- [ ] **Step 1: Write failing test for models**

Create `tests/unit/test_models.py`:

```python
from src.models.schemas import User, Session, Message, Document, DocumentChunk

def test_models_have_expected_columns():
    # Spec §3 — verify column existence
    user_cols = {c.name for c in User.__table__.columns}
    assert {"id", "name", "created_at"} <= user_cols

    session_cols = {c.name for c in Session.__table__.columns}
    assert {"id", "user_id", "created_at", "last_active_at",
            "summary", "summary_until_message_id"} <= session_cols

    message_cols = {c.name for c in Message.__table__.columns}
    assert {"id", "session_id", "role", "content",
            "tool_calls", "tool_call_id", "citations", "created_at"} <= message_cols

    doc_cols = {c.name for c in Document.__table__.columns}
    assert {"id", "user_id", "session_id", "filename", "page_count",
            "byte_size", "status", "error_message", "progress_page",
            "uploaded_at", "ingestion_started_at"} <= doc_cols

    chunk_cols = {c.name for c in DocumentChunk.__table__.columns}
    assert {"id", "document_id", "page_no", "chunk_idx",
            "content", "content_embedding", "token_count"} <= chunk_cols

def test_document_chunk_cascades():
    # Deleting a document cascades to its chunks
    fk = next(iter(DocumentChunk.__table__.foreign_keys))
    assert fk.ondelete == "CASCADE"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_models.py -v
```
Expected: ImportError on User/Session/etc.

- [ ] **Step 3: Implement models**

Replace `src/models/schemas.py`:

```python
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BIGINT, JSON, Column, DateTime, Enum as SAEnum, ForeignKey, Integer,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentStatus(str, Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_until_message_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(SAEnum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    page_count: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(SAEnum(DocumentStatus, name="document_status"), default=DocumentStatus.processing)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_page: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ingestion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    page_no: Mapped[int] = mapped_column(Integer)
    chunk_idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_embedding = mapped_column(Vector(1024))
    token_count: Mapped[int] = mapped_column(Integer)
```

- [ ] **Step 4: Verify model tests pass**

```bash
uv run pytest tests/unit/test_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Create alembic init migration**

Create `src/db/migrations/versions/0001_init.py`:

```python
"""init

Revision ID: 0001_init
Revises:
Create Date: 2026-04-25
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("summary_until_message_id", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", "tool", name="message_role"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_calls", JSONB, nullable=True),
        sa.Column("tool_call_id", sa.String(120), nullable=True),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("status", sa.Enum("processing", "ready", "failed", name="document_status"),
                  nullable=False, server_default="processing"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("progress_page", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ingestion_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_session_id", "documents", ["session_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("chunk_idx", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_embedding", Vector(1024), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING ivfflat (content_embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS document_status")
    op.execute("DROP TYPE IF EXISTS message_role")
```

- [ ] **Step 6: Rewrite test_db_smoke.py to verify migration**

Replace `tests/unit/test_db_smoke.py`:

```python
import pytest
from sqlalchemy import inspect, text
from src.db.session import get_engine

@pytest.mark.asyncio
async def test_migration_creates_all_tables():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))
        names = {row[0] for row in result.fetchall()}
        assert {"users", "sessions", "messages", "documents", "document_chunks"} <= names

@pytest.mark.asyncio
async def test_pgvector_extension_present():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'"))
        assert result.scalar() == "vector"
```

- [ ] **Step 7: Run alembic + smoke test**

```bash
# Bring postgres up via docker compose (only postgres service)
docker compose up -d postgres
sleep 3
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/chat \
  uv run alembic upgrade head

uv run pytest tests/unit/test_db_smoke.py -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/models/schemas.py src/db/migrations/versions/0001_init.py tests/unit/test_models.py tests/unit/test_db_smoke.py
git commit -m "feat(db): add 5-table schema with pgvector + ivfflat index"
```

---

## Task 2: PDF Parser

**Goal:** Wrap pdfplumber: open + count pages + iter (page_no, text). Used by upload validation + ingestion.

**Files:**
- Create: `src/ingest/pdf_parser.py`
- Test: `tests/unit/test_pdf_parser.py`
- Test fixture builder: `tests/fixtures/build_sample_pdf.py`

- [ ] **Step 1: Build a tiny Chinese PDF fixture script**

Create `tests/fixtures/build_sample_pdf.py`:

```python
"""Run once to create tests/fixtures/sample_zh.pdf for unit tests."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def build():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    out = Path(__file__).parent / "sample_zh.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("STSong-Light", 14)

    pages = [
        "第一页：腾讯 2025 年总营业收入为 6,605 亿元，同比增长 10.2%。",
        "第二页：本页空白用于测试空页跳过。",  # not actually empty, to keep extract_text non-None
        "第三页：金融科技及企业服务业务收入达到 2,134 亿元。",
    ]
    for text in pages:
        c.drawString(80, 750, text)
        c.showPage()
    c.save()

if __name__ == "__main__":
    build()
    print("Built", Path(__file__).parent / "sample_zh.pdf")
```

Run it once and commit the PDF as a fixture:
```bash
uv add --dev reportlab
uv run python tests/fixtures/build_sample_pdf.py
ls -la tests/fixtures/sample_zh.pdf
```

- [ ] **Step 2: Write failing test for parser**

Create `tests/unit/test_pdf_parser.py`:

```python
from pathlib import Path
import pytest
from src.ingest.pdf_parser import open_pdf_meta, iter_pages, PdfValidationError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"

def test_open_pdf_meta_returns_page_count():
    meta = open_pdf_meta(FIXTURE)
    assert meta.page_count == 3

def test_open_pdf_meta_rejects_corrupt(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(PdfValidationError, match="无法打开"):
        open_pdf_meta(bad)

def test_open_pdf_meta_rejects_empty(tmp_path):
    bad = tmp_path / "empty.pdf"
    bad.write_bytes(b"%PDF-1.4\n%%EOF")  # syntactically valid but 0 pages
    with pytest.raises(PdfValidationError, match="空 PDF"):
        open_pdf_meta(bad)

def test_iter_pages_yields_chinese_text():
    pages = list(iter_pages(FIXTURE))
    assert len(pages) == 3
    page_no, text = pages[0]
    assert page_no == 1
    assert "腾讯" in text and "6,605 亿元" in text
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_pdf_parser.py -v
```
Expected: ImportError on `src.ingest.pdf_parser`.

- [ ] **Step 4: Implement parser**

Create `src/ingest/pdf_parser.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pdfplumber


class PdfValidationError(Exception):
    """Upload-time validation failure (4xx for the API)."""


@dataclass
class PdfMeta:
    page_count: int


def open_pdf_meta(path: Path) -> PdfMeta:
    """Open + validate + return meta. Raises PdfValidationError on:
    - Corrupted/unreadable file → '无法打开 PDF（损坏？）'
    - Encrypted file → 'PDF 已加密'
    - Zero pages → '空 PDF'
    Spec §4.upload.validate
    """
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
    except Exception as e:
        # pdfplumber wraps PyPDF2; encrypted PDFs raise during open
        msg = str(e).lower()
        if "encrypt" in msg or "password" in msg:
            raise PdfValidationError("PDF 已加密")
        raise PdfValidationError(f"无法打开 PDF（损坏？）: {e}")
    if n == 0:
        raise PdfValidationError("空 PDF")
    return PdfMeta(page_count=n)


def iter_pages(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (page_no_1based, text). Empty pages yield ''.
    Caller decides whether to skip empty.
    """
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            yield i, page.extract_text() or ""
```

- [ ] **Step 5: Verify tests pass**

```bash
uv run pytest tests/unit/test_pdf_parser.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/build_sample_pdf.py tests/fixtures/sample_zh.pdf src/ingest/pdf_parser.py tests/unit/test_pdf_parser.py pyproject.toml uv.lock
git commit -m "feat(ingest): pdf_parser with chinese fixture + validation"
```

---

## Task 3: Chunker

**Goal:** Implement spec §4 chunker exactly: ≤500 token paragraphs aggregation, 80 overlap, page-bounded, with `_split_oversized` for long paragraphs/sentences. Cover all 8 edge cases.

**Files:**
- Create: `src/ingest/chunker.py`
- Test: `tests/unit/test_chunker.py`

- [ ] **Step 1: Write failing tests covering all 8 edges**

Create `tests/unit/test_chunker.py`:

```python
from src.ingest.chunker import chunk

# Use a deterministic mock token counter: 1 char = 1 token (simplifies math)
import src.ingest.chunker as ch
ch._token_count = len  # type: ignore   # see implementation note in Step 4


def test_case_1_blank_page():
    assert chunk("", page_no=1) == []
    assert chunk("   \n\n  \n", page_no=1) == []

def test_case_2_short_paragraph():
    out = chunk("第一段。", page_no=5)
    assert len(out) == 1
    assert out[0].page_no == 5
    assert "第一段" in out[0].content

def test_case_3_exactly_500():
    para = "x" * 500
    out = chunk(para, page_no=1)
    assert len(out) == 1
    assert len(out[0].content) == 500

def test_case_4_multiple_aggregated_with_overlap():
    p1 = "x" * 400
    p2 = "y" * 200   # 400 + 200 = 600 > 500 → split, 80 char overlap
    text = p1 + "\n\n" + p2
    out = chunk(text, page_no=1)
    assert len(out) >= 2
    # Each chunk ≤ 500
    assert all(len(c.content) <= 500 for c in out)
    # Adjacent chunks overlap (last 80 chars of chunk 1 appear in chunk 2)
    assert out[0].content[-80:] in out[1].content or "x" in out[1].content

def test_case_5_oversized_single_paragraph_split_by_sentences():
    sentences = "。".join(["a" * 200] * 5) + "。"   # 5 sentences of 200 chars
    out = chunk(sentences, page_no=1)
    assert all(len(c.content) <= 500 for c in out)
    assert len(out) >= 2

def test_case_6_tail_plus_para_degrades():
    # buf accumulates to 450, next para is 100 → tail(80)+100=180 fits
    # but if next para is 480 → tail(80)+480=560 > 500 → degrade to buf=para
    p1 = "x" * 450
    p2 = "y" * 480
    out = chunk(p1 + "\n\n" + p2, page_no=1)
    assert all(len(c.content) <= 500 for c in out)

def test_case_7_oversized_single_sentence_sliding_window():
    # Sentence with no punctuation, 1500 chars
    out = chunk("z" * 1500, page_no=1)
    assert all(len(c.content) <= 500 for c in out)
    assert len(out) >= 3

def test_case_8_split_oversized_candidate_overflow():
    # Inside _split_oversized: sentence s=480, after yielding tail(80)+s=560 should degrade
    # Build a paragraph whose internal sentences trigger the path
    long_para = ("a" * 480 + "。") * 3  # three sentences each 480 chars
    out = chunk(long_para, page_no=1)
    assert all(len(c.content) <= 500 for c in out)


def test_page_no_carried():
    out = chunk("一些内容。", page_no=42)
    assert out[0].page_no == 42
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/unit/test_chunker.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement chunker per spec §4**

Create `src/ingest/chunker.py`:

```python
from dataclasses import dataclass
from typing import Iterator
import re


MAX_TOKENS = 500
OVERLAP_TOKENS = 80


@dataclass
class Chunk:
    content: str
    page_no: int


def _token_count(s: str) -> int:
    """Char count is a workable proxy for Chinese-heavy text (1 CJK char ≈ 1 token).
    Tests monkey-patch this to len() for determinism. Production uses a tokenizer
    only if we observe drift; YAGNI for V1.
    """
    return len(s)


def _split_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_sentences(text: str) -> list[str]:
    # Chinese punctuation + newline. Keep delimiters attached to preceding sentence.
    parts = re.split(r"(?<=[。！？\n])", text)
    return [p for p in parts if p.strip()]


def _take_tail_tokens(s: str, n: int) -> str:
    return s[-n:] if len(s) > n else s


def chunk(text: str, page_no: int) -> list[Chunk]:
    """Per spec §4: ≤500 token, 80 overlap, page-bounded."""
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(Chunk(content=buf.strip(), page_no=page_no))
        buf = ""

    for para in paragraphs:
        para_tokens = _token_count(para)

        if para_tokens > MAX_TOKENS:
            flush()
            for piece in _split_oversized(para, MAX_TOKENS, OVERLAP_TOKENS):
                chunks.append(Chunk(content=piece, page_no=page_no))
            continue

        if _token_count(buf) + para_tokens <= MAX_TOKENS:
            buf += ("\n\n" if buf else "") + para
            continue

        # Overflow → flush current, start new with overlap
        tail = _take_tail_tokens(buf, OVERLAP_TOKENS)
        flush()
        candidate = (tail + "\n\n" + para) if tail else para
        if _token_count(candidate) > MAX_TOKENS:
            # Degrade: drop overlap, start fresh with para (known ≤ MAX)
            buf = para
        else:
            buf = candidate

    flush()
    return chunks


def _split_oversized(text: str, max_tokens: int, overlap: int) -> Iterator[str]:
    """Spec §4 _split_oversized: sentence-first, sliding-window fallback,
    candidate-overflow degrade."""
    sentences = _split_sentences(text)
    buf = ""
    for s in sentences:
        if _token_count(s) > max_tokens:
            if buf.strip():
                yield buf.strip()
                buf = ""
            for i in range(0, _token_count(s), max_tokens - overlap):
                yield s[i : i + max_tokens]
            continue
        if _token_count(buf) + _token_count(s) <= max_tokens:
            buf += s
        else:
            if buf.strip():
                yield buf.strip()
            candidate = _take_tail_tokens(buf, overlap) + s
            buf = candidate if _token_count(candidate) <= max_tokens else s
    if buf.strip():
        yield buf.strip()
```

- [ ] **Step 4: Verify all 8 cases pass**

```bash
uv run pytest tests/unit/test_chunker.py -v
```
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/chunker.py tests/unit/test_chunker.py
git commit -m "feat(ingest): chunker with 8-case coverage incl. oversize degrade"
```

---

## Task 4: Memory Service (sessions / messages / documents / chunks)

**Goal:** Build a thin async data-access layer used by API and engine. Single class `MemoryService(db)` with explicit methods. No insurance-domain code remains.

**Files:**
- Replace stub: `src/core/memory_service.py`
- Test: `tests/unit/test_memory_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_memory_service.py`:

```python
import pytest
from uuid import uuid4
from src.core.memory_service import MemoryService
from src.models.schemas import DocumentStatus

@pytest.fixture
async def mem(db_session):
    return MemoryService(db_session)

@pytest.fixture
async def user(mem):
    return await mem.upsert_demo_user()

@pytest.fixture
async def session_obj(mem, user):
    return await mem.create_session(user.id)

@pytest.mark.asyncio
async def test_create_session_and_list(mem, user):
    s1 = await mem.create_session(user.id)
    s2 = await mem.create_session(user.id)
    rows = await mem.list_sessions(user.id, limit=10)
    assert {r.id for r in rows} == {s1.id, s2.id}

@pytest.mark.asyncio
async def test_create_document_returns_full_meta(mem, user, session_obj):
    doc = await mem.create_document(
        user_id=user.id, session_id=session_obj.id,
        filename="test.pdf", page_count=10, byte_size=12345,
    )
    assert doc.status == DocumentStatus.processing
    assert doc.page_count == 10
    assert doc.progress_page == 0

@pytest.mark.asyncio
async def test_update_document_progress_and_status(mem, user, session_obj):
    doc = await mem.create_document(
        user_id=user.id, session_id=session_obj.id,
        filename="x.pdf", page_count=5, byte_size=100,
    )
    await mem.update_document(doc.id, progress_page=3)
    refreshed = await mem.get_document(doc.id)
    assert refreshed.progress_page == 3
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    refreshed = await mem.get_document(doc.id)
    assert refreshed.status == DocumentStatus.ready

@pytest.mark.asyncio
async def test_list_documents_for_session(mem, user, session_obj):
    s2 = await mem.create_session(user.id)
    d1 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="a.pdf", page_count=1, byte_size=1)
    d2 = await mem.create_document(user_id=user.id, session_id=s2.id,
                                    filename="b.pdf", page_count=1, byte_size=1)
    rows = await mem.list_documents(session_obj.id)
    assert {r.id for r in rows} == {d1.id}

@pytest.mark.asyncio
async def test_count_documents_by_status(mem, user, session_obj):
    d1 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="a.pdf", page_count=1, byte_size=1)
    d2 = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                    filename="b.pdf", page_count=1, byte_size=1)
    await mem.update_document(d1.id, status=DocumentStatus.ready)
    counts = await mem.count_documents_by_status(session_obj.id)
    assert counts == {"processing": 1, "ready": 1, "failed": 0}

@pytest.mark.asyncio
async def test_bulk_insert_chunks_and_search(mem, user, session_obj):
    doc = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                     filename="a.pdf", page_count=2, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "腾讯营收 6605 亿元",
         "embedding": [0.1] * 1024, "token_count": 10},
        {"page_no": 2, "chunk_idx": 1, "content": "阿里营收 9000 亿元",
         "embedding": [0.2] * 1024, "token_count": 10},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    hits = await mem.search_chunks(session_obj.id, query_embedding=[0.1] * 1024,
                                    top_k=10, min_similarity=0.0)
    assert len(hits) == 2

@pytest.mark.asyncio
async def test_delete_document_cascades_chunks_but_keeps_message_citations(
    mem, user, session_obj
):
    doc = await mem.create_document(user_id=user.id, session_id=session_obj.id,
                                     filename="a.pdf", page_count=1, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "x",
         "embedding": [0.0] * 1024, "token_count": 1},
    ])
    citations = [{"doc_id": str(doc.id), "filename": "a.pdf",
                  "page_no": 1, "snippet": "x", "score": 0.9}]
    await mem.save_assistant_message(session_obj.id, "answer", citations=citations)

    await mem.delete_document(doc.id)

    # chunks gone (CASCADE), but message.citations preserved
    assert await mem.get_document(doc.id) is None
    msgs = await mem.list_messages(session_obj.id)
    assert msgs[-1].citations == citations
```

- [ ] **Step 2: Add async db_session fixture**

Edit `tests/conftest.py` (create if absent), append:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_sessionmaker

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    Sessionmaker = get_sessionmaker()
    async with Sessionmaker() as session:
        yield session
        await session.rollback()
```

- [ ] **Step 3: Run tests to verify failure**

```bash
docker compose up -d postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat \
  uv run pytest tests/unit/test_memory_service.py -v
```
Expected: ImportError / AttributeError.

- [ ] **Step 4: Implement MemoryService**

Replace `src/core/memory_service.py`:

```python
from typing import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
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
            out[status.value if hasattr(status, "value") else status] = n
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
        # pgvector: <=> is cosine distance; similarity = 1 - distance
        sql = """
        SELECT dc.document_id, d.filename, dc.page_no, dc.content,
               1 - (dc.content_embedding <=> CAST(:qvec AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.session_id = :sid AND d.status = 'ready'
        ORDER BY dc.content_embedding <=> CAST(:qvec AS vector)
        LIMIT :top_k
        """
        from sqlalchemy import text
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
```

- [ ] **Step 5: Run alembic + verify tests pass**

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/chat \
  uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat \
  uv run pytest tests/unit/test_memory_service.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core/memory_service.py tests/unit/test_memory_service.py tests/conftest.py
git commit -m "feat(memory): MemoryService for sessions/messages/documents/chunks"
```

---

## Task 5: Ingestion Pipeline

**Goal:** Implement spec §4 ingestion: `_ingest_document`, `_mark_failed_and_clean`, `_ingest_with_timeout`, plus `cleanup_stale_documents` for startup hook. Pure functions taking deps as args (memory, embedder, parser, chunker) — easy to test.

**Files:**
- Create: `src/ingest/ingestion.py`
- Test: `tests/unit/test_ingestion_scanned.py`
- Test: `tests/unit/test_ingestion_failure_cleanup.py`
- Test: `tests/unit/test_startup_recovery.py`

- [ ] **Step 1: Write failing tests for the three failure paths + scanned + startup recovery**

Create `tests/unit/test_ingestion_scanned.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from src.ingest.ingestion import _ingest_document
from src.models.schemas import DocumentStatus

@pytest.mark.asyncio
async def test_scanned_pdf_marks_failed():
    # All pages return empty text → total_chunks == 0 → failed
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    parser = lambda path: iter([(1, ""), (2, ""), (3, "")])
    chunker = lambda text, page_no: []

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=parser, chunker=chunker)

    # _mark_failed_and_clean called: delete chunks then update status
    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    mem.update_document.assert_any_await(
        "doc-id", status=DocumentStatus.failed,
        error_message=pytest.approx_str("未能从 PDF 中提取任何文本"),
        progress_page=0,
    )
```

(Plan note: `pytest.approx_str` is not built-in — define helper inline:
```python
def approx_str(needle):
    class _A:
        def __eq__(self, other): return needle in str(other)
    return _A()
pytest.approx_str = approx_str
```
Add this to `tests/conftest.py`.)

Create `tests/unit/test_ingestion_failure_cleanup.py`:

```python
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from src.ingest.ingestion import _ingest_document, _ingest_with_timeout
from src.models.schemas import DocumentStatus


@pytest.mark.asyncio
async def test_midrun_exception_cleans_partial_chunks():
    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.encode_batch = MagicMock(side_effect=[[1.0]*1024, RuntimeError("boom")])
    parser = lambda path: iter([(1, "p1"), (2, "p2")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=parser, chunker=chunker)

    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    # Last update_document call sets status=failed
    last_call = mem.update_document.await_args_list[-1]
    assert last_call.kwargs.get("status") == DocumentStatus.failed
    assert "boom" in last_call.kwargs.get("error_message", "")


@pytest.mark.asyncio
async def test_timeout_cleans_partial_chunks():
    mem = MagicMock()
    mem.delete_chunks_for_document = AsyncMock()
    mem.update_document = AsyncMock()

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    # Patch _ingest_document to be slow; _ingest_with_timeout wraps with 0.1s timeout
    from src.ingest import ingestion as ing
    ing._ingest_document = slow

    await _ingest_with_timeout("doc-id", path=Path("/tmp/x.pdf"),
                                mem=mem, embedder=MagicMock(),
                                iter_pages=lambda p: iter([]),
                                chunker=lambda t, n: [],
                                timeout=0.1)

    mem.delete_chunks_for_document.assert_awaited_once_with("doc-id")
    last = mem.update_document.await_args_list[-1]
    assert last.kwargs.get("status") == DocumentStatus.failed
    assert "超时" in last.kwargs.get("error_message", "")
```

Create `tests/unit/test_startup_recovery.py`:

```python
import pytest
from src.ingest.ingestion import cleanup_stale_documents
from src.models.schemas import DocumentStatus

@pytest.mark.asyncio
async def test_stale_processing_marked_failed_and_chunks_purged(db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    # Insert a "stale" processing doc with partial chunks
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=10, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "p1",
         "embedding": [0.0]*1024, "token_count": 1},
    ])
    # ensure status is processing (default)
    refreshed = await mem.get_document(doc.id)
    assert refreshed.status == DocumentStatus.processing

    await cleanup_stale_documents(mem)

    # status flipped + chunks deleted
    after = await mem.get_document(doc.id)
    assert after.status == DocumentStatus.failed
    assert "解析中断" in after.error_message
    # chunks gone
    hits = await mem.search_chunks(sess.id, query_embedding=[0.0]*1024,
                                    top_k=10, min_similarity=0.0)
    assert hits == []
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/unit/test_ingestion_scanned.py tests/unit/test_ingestion_failure_cleanup.py tests/unit/test_startup_recovery.py -v
```
Expected: ImportError on `src.ingest.ingestion`.

- [ ] **Step 3: Implement ingestion module**

Create `src/ingest/ingestion.py`:

```python
"""Ingestion pipeline. Pure-ish functions: deps injected.
Spec §4 (ingestion + startup recovery)."""
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
    chunker: Callable[[str, int], list[dict]],
) -> None:
    """Run full ingestion. On any error, calls _mark_failed_and_clean.
    chunker returns list of {content, page_no}; this function adds chunk_idx + embedding.
    """
    chunk_idx = 0
    total_chunks = 0
    try:
        for page_no, text in iter_pages(path):
            chunks = chunker(text, page_no=page_no)
            if chunks:
                contents = [c["content"] for c in chunks]
                embeddings = embedder.encode_batch(contents)
                rows = [
                    {
                        "page_no": page_no,
                        "chunk_idx": chunk_idx + i,
                        "content": c["content"],
                        "embedding": list(emb) if not isinstance(emb, list) else emb,
                        "token_count": len(c["content"]),
                    }
                    for i, (c, emb) in enumerate(zip(chunks, embeddings))
                ]
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
    then mark failed with '解析中断'. Single transaction in production; with
    MemoryService two awaited calls are acceptable for V1.
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
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/unit/test_ingestion_scanned.py tests/unit/test_ingestion_failure_cleanup.py tests/unit/test_startup_recovery.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/ingestion.py tests/unit/test_ingestion_*.py tests/unit/test_startup_recovery.py tests/conftest.py
git commit -m "feat(ingest): pipeline with unified failure cleanup + startup recovery"
```

---

## Task 6: Documents API — Upload (with temp/atomic rename)

**Goal:** Implement `POST /sessions/{session_id}/documents` per spec §4. Temp-path + atomic-rename pattern; all failure paths clean up.

**Files:**
- Create: `src/api/documents.py`
- Modify: `src/main.py` (mount documents router)
- Test: `tests/unit/test_api_documents.py`

- [ ] **Step 1: Write failing tests for upload happy + 5 reject paths + temp cleanup**

Create `tests/unit/test_api_documents.py`:

```python
from pathlib import Path
import pytest
from httpx import AsyncClient
from src.main import make_app_default

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"

@pytest.fixture
async def client():
    app = make_app_default()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c

@pytest.fixture
async def session_id(client):
    r = await client.post("/sessions")
    return r.json()["session_id"]

@pytest.mark.asyncio
async def test_upload_happy(client, session_id):
    files = {"file": ("sample.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "processing"
    assert body["page_count"] == 3
    assert "document_id" in body

@pytest.mark.asyncio
async def test_upload_rejects_non_pdf_extension(client, session_id):
    files = {"file": ("foo.txt", b"hi", "text/plain")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    assert "扩展名" in r.json()["detail"] or "PDF" in r.json()["detail"]

@pytest.mark.asyncio
async def test_upload_rejects_oversize(client, session_id):
    big = b"%PDF-1.4\n" + (b"x" * (21 * 1024 * 1024))
    files = {"file": ("big.pdf", big, "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    assert "20" in r.json()["detail"]

@pytest.mark.asyncio
async def test_upload_rejects_corrupt_pdf(client, session_id):
    files = {"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    assert "无法打开" in r.json()["detail"]

@pytest.mark.asyncio
async def test_upload_rejects_unknown_session(client):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post("/sessions/00000000-0000-0000-0000-000000000099/documents",
                          files=files)
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_upload_failure_cleans_temp(client, session_id, tmp_path, monkeypatch):
    # Force validation to fail; assert no leftover in .tmp
    files = {"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    await client.post(f"/sessions/{session_id}/documents", files=files)

    tmp_dir = Path("data/uploads/.tmp")
    leftovers = list(tmp_dir.glob("*.pdf")) if tmp_dir.exists() else []
    assert leftovers == [], f"leftover temp files: {leftovers}"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/unit/test_api_documents.py -v
```
Expected: 404 / 405 / ImportError.

- [ ] **Step 3: Implement documents API**

Create `src/api/documents.py`:

```python
import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_config
from src.core.memory_service import MemoryService, DEMO_USER_ID
from src.db.session import get_db
from src.embedding.bge_embedder import BgeEmbedder
from src.ingest.chunker import chunk
from src.ingest.ingestion import _ingest_with_timeout
from src.ingest.pdf_parser import iter_pages, open_pdf_meta, PdfValidationError

UPLOADS_DIR = Path("data/uploads")
TMP_DIR = UPLOADS_DIR / ".tmp"


def make_documents_router(*, embedder: BgeEmbedder) -> APIRouter:
    router = APIRouter()
    cfg = get_config()
    upload_max_bytes = cfg["ingestion"]["upload_max_bytes"]
    timeout = cfg["ingestion"]["ingestion_timeout_seconds"]

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
        if len(body) > upload_max_bytes:
            raise HTTPException(400, f"文件超过 20 MB 限制")
        temp_path.write_bytes(body)

        # 4) validate
        try:
            meta = open_pdf_meta(temp_path)
        except PdfValidationError as e:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(400, str(e))

        # 5) INSERT documents
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
            import os
            os.replace(temp_path, final_path)
        except Exception:
            await mem.delete_document(document_id)
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "文件落盘失败")

        # 7) launch background ingestion
        asyncio.create_task(_ingest_with_timeout(
            document_id, path=final_path, mem=mem, embedder=embedder,
            iter_pages=iter_pages, chunker=chunk, timeout=timeout,
        ))

        # 8) return
        return {
            "document_id": str(document_id),
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "page_count": doc.page_count,
        }

    return router
```

- [ ] **Step 4: Wire router in main.py**

Edit `src/main.py`. Inside `make_app_default()` after the existing chat router mount, add:

```python
from src.api.documents import make_documents_router
documents_router = make_documents_router(embedder=deps["embedder"])
app.include_router(documents_router)
```

- [ ] **Step 5: Verify tests pass**

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat \
  uv run pytest tests/unit/test_api_documents.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/api/documents.py src/main.py tests/unit/test_api_documents.py
git commit -m "feat(api): document upload with temp+atomic-rename + cleanup invariants"
```

---

## Task 7: Documents API — List, Delete, Progress SSE

**Goal:** Add `GET /documents`, `DELETE /documents/{id}` (with 409 for processing), `GET /progress` SSE.

**Files:**
- Modify: `src/api/documents.py` (extend the router)
- Test: `tests/unit/test_delete_document.py`
- Extend: `tests/unit/test_api_documents.py` (list + progress)

- [ ] **Step 1: Write failing tests for delete + list + progress**

Create `tests/unit/test_delete_document.py`:

```python
import pytest
from pathlib import Path
from httpx import AsyncClient
from src.main import make_app_default
from src.models.schemas import DocumentStatus

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"

@pytest.fixture
async def client():
    app = make_app_default()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c

async def _upload(client, session_id):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    return r.json()["document_id"]

@pytest.mark.asyncio
async def test_delete_processing_returns_409(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    # status defaults to processing

    r = await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")
    assert r.status_code == 409
    assert "解析中" in r.json()["detail"]

@pytest.mark.asyncio
async def test_delete_ready_succeeds_and_cascades(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "x",
         "embedding": [0.0]*1024, "token_count": 1},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    r = await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")
    assert r.status_code == 204

    assert await mem.get_document(doc.id) is None
    hits = await mem.search_chunks(sess.id, query_embedding=[0.0]*1024,
                                    top_k=10, min_similarity=0.0)
    assert hits == []

@pytest.mark.asyncio
async def test_delete_unknown_returns_404(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    r = await client.delete(f"/sessions/{sess.id}/documents/00000000-0000-0000-0000-000000000099")
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_delete_preserves_message_citations(client, db_session):
    from src.core.memory_service import MemoryService
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    await mem.update_document(doc.id, status=DocumentStatus.ready)
    citations = [{"doc_id": str(doc.id), "filename": "x.pdf",
                  "page_no": 1, "snippet": "hello", "score": 0.9}]
    await mem.save_assistant_message(sess.id, "answer", citations=citations)

    await client.delete(f"/sessions/{sess.id}/documents/{doc.id}")

    msgs = await mem.list_messages(sess.id)
    assert msgs[-1].citations == citations
```

Append to `tests/unit/test_api_documents.py`:

```python
@pytest.mark.asyncio
async def test_list_documents(client, session_id):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    await client.post(f"/sessions/{session_id}/documents", files=files)
    r = await client.get(f"/sessions/{session_id}/documents")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert "filename" in rows[0] and "status" in rows[0] and "page_count" in rows[0]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/unit/test_delete_document.py tests/unit/test_api_documents.py -v
```
Expected: 405 / 404 on new endpoints.

- [ ] **Step 3: Extend documents.py with list / delete / progress**

Append to `make_documents_router()` in `src/api/documents.py`:

```python
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
                409, "文档正在解析中，请等待完成或解析超时（≤5min）后再删除"
            )

        await mem.delete_document(document_id)
        try:
            (UPLOADS_DIR / f"{document_id}.pdf").unlink(missing_ok=True)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("failed to unlink %s.pdf", document_id)

    @router.get("/sessions/{session_id}/documents/{document_id}/progress")
    async def progress_stream(
        session_id: UUID, document_id: UUID, db: AsyncSession = Depends(get_db),
    ):
        from fastapi.responses import StreamingResponse
        import json

        async def gen():
            mem = MemoryService(db)
            while True:
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
                payload = {"page": doc.progress_page,
                           "total": doc.page_count, "phase": "ingesting"}
                yield "event: progress\ndata: " + json.dumps(payload) + "\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/unit/test_delete_document.py tests/unit/test_api_documents.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/documents.py tests/unit/test_delete_document.py tests/unit/test_api_documents.py
git commit -m "feat(api): list/delete documents (409 on processing) + progress SSE"
```

---

## Task 8: Startup Recovery Hook

**Goal:** Wire `cleanup_stale_documents` into FastAPI startup so any process restart resets stale `processing` rows.

**Files:**
- Modify: `src/main.py`
- Test: existing `tests/unit/test_startup_recovery.py` (already covers the helper; add an integration assertion)

- [ ] **Step 1: Add startup hook**

In `src/main.py` `make_app_default()`, after `app = FastAPI(...)` add:

```python
@app.on_event("startup")
async def _cleanup_stale_documents_on_startup():
    from src.ingest.ingestion import cleanup_stale_documents
    Sessionmaker = deps["sessionmaker"]
    async with Sessionmaker() as db:
        mem = MemoryService(db)
        await cleanup_stale_documents(mem)
```

- [ ] **Step 2: Add integration assertion**

Append to `tests/unit/test_startup_recovery.py`:

```python
@pytest.mark.asyncio
async def test_app_startup_invokes_cleanup(db_session):
    from src.core.memory_service import MemoryService
    from httpx import AsyncClient
    from src.main import make_app_default

    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="x.pdf", page_count=1, byte_size=1)
    # default processing

    app = make_app_default()
    async with AsyncClient(app=app, base_url="http://test"):
        # entering context triggers startup
        pass

    after = await mem.get_document(doc.id)
    assert after.status == DocumentStatus.failed
```

- [ ] **Step 3: Verify**

```bash
uv run pytest tests/unit/test_startup_recovery.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/main.py tests/unit/test_startup_recovery.py
git commit -m "feat(main): startup hook clears stale processing docs"
```

---

## Task 9: Search Documents Tool

**Goal:** Sole tool registered in V1. Per spec §5: BGE-encode query → top-K via pgvector → filter by `MIN_SIMILARITY` → return `{ok, found, chunks}`.

**Files:**
- Create: `src/tools/search_documents.py`
- Modify: `src/core/tool_registry.py`
- Modify: `src/embedding/bge_embedder.py` (add `encode_one` if absent)
- Test: `tests/unit/test_search_documents.py`

> **Interface note:** Tests assume `BgeEmbedder.encode_one(text: str) -> list[float]`. If the scaffold only has `encode_batch(texts: list[str]) -> list[list[float]]`, add a one-liner: `def encode_one(self, t): return self.encode_batch([t])[0]`.

- [ ] **Step 1: Failing tests**

Create `tests/unit/test_search_documents.py`:

```python
import pytest
from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA
from src.models.schemas import DocumentStatus

@pytest.mark.asyncio
async def test_schema_has_query_param():
    assert TOOL_SCHEMA["name"] == "search_documents"
    assert "query" in TOOL_SCHEMA["parameters"]["properties"]

@pytest.mark.asyncio
async def test_returns_found_true_when_chunks_above_threshold(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="rep.pdf", page_count=1, byte_size=1)
    embedder = BgeEmbedder()
    text = "腾讯 2025 年总营业收入为 6,605 亿元"
    emb = embedder.encode_one(text)
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 12, "chunk_idx": 0, "content": text,
         "embedding": list(emb), "token_count": 20},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.0, top_k=8)
    out = await tool.execute(session_id=sess.id, query="腾讯 2025 年总营收")
    assert out["ok"] is True and out["found"] is True
    assert out["chunks"][0]["page_no"] == 12

@pytest.mark.asyncio
async def test_returns_found_false_when_all_below_threshold(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    sess = await mem.create_session(user.id)
    doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                     filename="rep.pdf", page_count=1, byte_size=1)
    embedder = BgeEmbedder()
    emb = embedder.encode_one("腾讯财报内容")
    await mem.bulk_insert_chunks(doc.id, [
        {"page_no": 1, "chunk_idx": 0, "content": "腾讯财报内容",
         "embedding": list(emb), "token_count": 10},
    ])
    await mem.update_document(doc.id, status=DocumentStatus.ready)

    # very high threshold → guaranteed empty
    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.99, top_k=8)
    out = await tool.execute(session_id=sess.id, query="完全无关的话题")
    assert out["ok"] is True and out["found"] is False
    assert out["chunks"] == []

@pytest.mark.asyncio
async def test_isolation_between_sessions(db_session):
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder
    mem = MemoryService(db_session)
    user = await mem.upsert_demo_user()
    s1 = await mem.create_session(user.id)
    s2 = await mem.create_session(user.id)
    embedder = BgeEmbedder()

    for sess in [s1, s2]:
        doc = await mem.create_document(user_id=user.id, session_id=sess.id,
                                         filename="x.pdf", page_count=1, byte_size=1)
        emb = embedder.encode_one(f"内容 {sess.id}")
        await mem.bulk_insert_chunks(doc.id, [
            {"page_no": 1, "chunk_idx": 0, "content": f"内容 {sess.id}",
             "embedding": list(emb), "token_count": 5},
        ])
        await mem.update_document(doc.id, status=DocumentStatus.ready)

    tool = SearchDocumentsTool(mem=mem, embedder=embedder,
                                min_similarity=0.0, top_k=10)
    out = await tool.execute(session_id=s1.id, query="内容")
    for c in out["chunks"]:
        # verify no s2 chunks leaked in
        assert str(s2.id) not in c["content"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/unit/test_search_documents.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement tool**

Create `src/tools/search_documents.py`:

```python
from uuid import UUID

TOOL_SCHEMA = {
    "name": "search_documents",
    "description": (
        "在用户当前会话已上传的 PDF 中检索相关段落。"
        "回答任何关于文档内容的问题前必须先调用此工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "中文检索 query，可以是用户原问题或提取的关键词",
            }
        },
        "required": ["query"],
    },
}


def _to_snippet(content: str, max_chars: int = 480) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "…"


class SearchDocumentsTool:
    """Spec §5 + §7 Citation DTO."""

    def __init__(self, *, mem, embedder, min_similarity: float, top_k: int):
        self.mem = mem
        self.embedder = embedder
        self.min_similarity = min_similarity
        self.top_k = top_k

    async def execute(self, *, session_id: UUID, query: str) -> dict:
        emb = self.embedder.encode_one(query)
        hits = await self.mem.search_chunks(
            session_id, query_embedding=list(emb),
            top_k=self.top_k, min_similarity=self.min_similarity,
        )
        if not hits:
            return {"ok": True, "found": False, "chunks": []}

        # de-dupe consecutive same-doc-same-page
        deduped = []
        seen = set()
        for h in hits:
            key = (h["doc_id"], h["page_no"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)

        chunks = [
            {
                "doc_id": h["doc_id"],
                "filename": h["filename"],
                "page_no": h["page_no"],
                "content": h["content"],
                "snippet": _to_snippet(h["content"]),
                "score": h["score"],
            }
            for h in deduped
        ]
        return {"ok": True, "found": True, "chunks": chunks}
```

- [ ] **Step 4: Register in tool_registry.py**

Replace contents of `src/core/tool_registry.py`:

```python
"""Tool registry — V1 has only search_documents."""
from typing import Any
from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA


class ToolRegistry:
    def __init__(self, *, mem, embedder, min_similarity: float, top_k: int):
        self._tools = {
            "search_documents": SearchDocumentsTool(
                mem=mem, embedder=embedder,
                min_similarity=min_similarity, top_k=top_k,
            ),
        }

    def schemas(self) -> list[dict]:
        return [TOOL_SCHEMA]

    async def execute(self, name: str, arguments: dict, *, session_id) -> dict:
        if name not in self._tools:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            return await self._tools[name].execute(session_id=session_id, **arguments)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
```

- [ ] **Step 5: Verify tests pass**

```bash
uv run pytest tests/unit/test_search_documents.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tools/search_documents.py src/core/tool_registry.py tests/unit/test_search_documents.py
git commit -m "feat(tools): search_documents with similarity threshold + Citation snippet"
```

---

## Task 10: Prompt Templates (4 variants)

**Goal:** Implement state-machine selection for templates A / B-EMPTY / B-PROCESSING / B-FAILED per spec §6. All four standard responses match exactly the table in spec §1.

**Files:**
- Replace: `src/core/prompt_templates.py`
- Test: `tests/unit/test_prompt_templates.py`

- [ ] **Step 1: Failing tests for selection + exact text**

Create `tests/unit/test_prompt_templates.py`:

```python
from src.core.prompt_templates import (
    select_template, render_system_prompt, FIXED_RESPONSES,
)

def test_fixed_responses_match_spec_exact():
    assert FIXED_RESPONSES["B-EMPTY"] == "请先上传 PDF 文档以开始提问。"
    assert FIXED_RESPONSES["B-PROCESSING"] == "文档正在解析中，请稍候再提问。"
    assert FIXED_RESPONSES["B-FAILED"] == "已上传的文档解析失败，请删除后重新上传。"
    assert FIXED_RESPONSES["NO_MATCH"] == "在已上传文档中未找到相关信息。"

def test_select_template_a_when_ready_geq_1():
    assert select_template({"ready": 1, "processing": 0, "failed": 0}) == "A"
    assert select_template({"ready": 1, "processing": 1, "failed": 1}) == "A"

def test_select_template_b_empty_when_no_docs():
    assert select_template({"ready": 0, "processing": 0, "failed": 0}) == "B-EMPTY"

def test_select_template_b_processing_when_has_processing_no_ready():
    assert select_template({"ready": 0, "processing": 1, "failed": 0}) == "B-PROCESSING"
    # mix: processing + failed → still B-PROCESSING per spec
    assert select_template({"ready": 0, "processing": 1, "failed": 2}) == "B-PROCESSING"

def test_select_template_b_failed_when_only_failed():
    assert select_template({"ready": 0, "processing": 0, "failed": 1}) == "B-FAILED"

def test_render_template_a_includes_filenames():
    docs = [{"filename": "x.pdf", "page_count": 10}]
    p = render_system_prompt("A", docs=docs, persona="你是助手")
    assert "你是助手" in p
    assert "x.pdf" in p and "10" in p
    assert "search_documents" in p

def test_render_template_b_returns_marker():
    p = render_system_prompt("B-EMPTY", docs=[], persona="你是助手")
    # B templates also include the persona to keep voice consistent
    assert "你是助手" in p
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/test_prompt_templates.py -v
```
Expected: AttributeError on `FIXED_RESPONSES`.

- [ ] **Step 3: Implement templates**

Replace `src/core/prompt_templates.py`:

```python
"""Spec §6: prompt templates A / B-EMPTY / B-PROCESSING / B-FAILED."""

FIXED_RESPONSES = {
    "B-EMPTY":      "请先上传 PDF 文档以开始提问。",
    "B-PROCESSING": "文档正在解析中，请稍候再提问。",
    "B-FAILED":     "已上传的文档解析失败，请删除后重新上传。",
    "NO_MATCH":     "在已上传文档中未找到相关信息。",
}


def select_template(counts: dict[str, int]) -> str:
    ready = counts.get("ready", 0)
    processing = counts.get("processing", 0)
    failed = counts.get("failed", 0)
    if ready >= 1:
        return "A"
    if processing >= 1:
        return "B-PROCESSING"
    if failed >= 1:
        return "B-FAILED"
    return "B-EMPTY"


_A_TEMPLATE = """{persona}

你是一个文档问答助手。

【可用文档】
{doc_list}

【行为规则】
1. 任何用户问题都必须先调用 search_documents 工具检索
2. 工具返回 found=false 或 chunks 为空时，必须**完整、原样**回答：
   "{no_match}"
   不要补充猜测、不要解释为什么没找到、不要给替代答案
3. 工具返回 found=true 时，只能基于这些 chunks 的内容作答；
   不得使用你的常识或训练知识补充
4. 不要在回答正文中标注 [1] [2] 这类引用，前端会自动渲染来源卡片
5. 用简洁、专业的中文回答；数字保留报告中的精度
"""


def render_system_prompt(template: str, *, docs: list[dict], persona: str) -> str:
    if template == "A":
        doc_lines = "\n".join(
            f"- {d['filename']}（共 {d['page_count']} 页）" for d in docs
        ) or "（无）"
        return _A_TEMPLATE.format(
            persona=persona, doc_list=doc_lines,
            no_match=FIXED_RESPONSES["NO_MATCH"],
        )
    # B-* templates: persona + the fixed sentence is the full assistant reply,
    # but we still pass a system prompt so persona stays consistent if anything
    # ever does call the LLM with template B.
    return f"{persona}\n\n（系统提示：{FIXED_RESPONSES[template]}）"
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/unit/test_prompt_templates.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/prompt_templates.py tests/unit/test_prompt_templates.py
git commit -m "feat(prompt): 4 templates A/B-EMPTY/B-PROCESSING/B-FAILED with exact spec text"
```

---

## Task 11: Citation DTO + SSE `citations` Event

**Goal:** Add `Citation` Pydantic model + extend `StreamEvent` with `citations` variant + ensure encoder handles it. Spec §7.

**Files:**
- Modify: `src/api/sse.py`
- Test: extend `tests/unit/test_sse.py`

- [ ] **Step 1: Failing test**

Append to `tests/unit/test_sse.py`:

```python
import json
from src.api.sse import StreamEvent, encode_sse

def test_citations_event_encoding():
    chunks = [
        {"doc_id": "abc", "filename": "腾讯.pdf", "page_no": 12,
         "snippet": "营业收入 6,605 亿…", "score": 0.83},
    ]
    ev = StreamEvent.citations(chunks=chunks)
    raw = encode_sse(ev)
    assert raw.startswith("event: citations\n")
    payload = raw.split("data: ", 1)[1].strip()
    parsed = json.loads(payload)
    assert parsed["chunks"][0]["page_no"] == 12

def test_citations_event_empty_chunks():
    ev = StreamEvent.citations(chunks=[])
    raw = encode_sse(ev)
    assert "event: citations" in raw
    assert '"chunks": []' in raw or '"chunks":[]' in raw
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/test_sse.py -v
```
Expected: AttributeError on `StreamEvent.citations`.

- [ ] **Step 3: Add citations classmethod**

Inside `src/api/sse.py`'s `StreamEvent` class, add:

```python
    @classmethod
    def citations(cls, chunks: list[dict]) -> "StreamEvent":
        return cls(type="citations", data={"chunks": chunks})
```

(If `StreamEvent` is a dataclass, the classmethod still works on it; if it's a named tuple, switch to a dataclass with `type: str` and `data: dict` fields.)

- [ ] **Step 4: Verify**

```bash
uv run pytest tests/unit/test_sse.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/sse.py tests/unit/test_sse.py
git commit -m "feat(sse): add citations stream event"
```

---

## Task 12: ConversationEngine — 4-Template Dispatch + Structured Citations

**Goal:** Rewrite engine so it: (1) chooses template via `select_template`, (2) for B-* short-circuits to fixed response + empty citations, (3) for A runs LLM with tools, collects all chunks where `found=true`, (4) emits `text → citations(empty or collected) → done` always.

**Files:**
- Replace: `src/core/conversation_engine.py`
- Test: `tests/unit/test_conversation_engine.py`

- [ ] **Step 1: Failing tests**

Create `tests/unit/test_conversation_engine.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.conversation_engine import ConversationEngine

@pytest.mark.asyncio
async def test_b_empty_emits_fixed_text_and_empty_citations():
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 0, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=MagicMock(), tools=MagicMock(),
                                 persona="助手")
    events = []
    async for ev in engine.handle_stream(session_id="sid", message="hi"):
        events.append(ev)

    types = [e.type for e in events]
    assert "text" in types and "citations" in types and "done" in types
    text_ev = next(e for e in events if e.type == "text")
    assert "请先上传" in "".join(
        e.data.get("delta", "") for e in events if e.type == "text"
    )
    cit_ev = next(e for e in events if e.type == "citations")
    assert cit_ev.data["chunks"] == []

@pytest.mark.asyncio
async def test_b_processing_emits_processing_text():
    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 0, "processing": 1, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    engine = ConversationEngine(mem=mem, llm=MagicMock(), tools=MagicMock(),
                                 persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="hi")]
    full = "".join(e.data.get("delta", "") for e in events if e.type == "text")
    assert "正在解析中" in full

@pytest.mark.asyncio
async def test_template_a_with_tool_found_true_emits_citations():
    """Mock LLM to call search_documents once, mock tool to return found=true."""
    from src.api.sse import StreamEvent

    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        def __init__(self, id, name=None, arguments=None):
            self.id, self.name, self.arguments = id, name, arguments

    async def fake_chat_stream(messages, tools):
        # First call: emit a tool call
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                id="t1", name="search_documents", arguments='{"query":"营收"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            # Second call after tool result: produce final answer
            yield _LLMChunk(text_delta="腾讯 2025 年总营收为 6,605 亿元。")
            yield _LLMChunk(finish_reason="stop")

    llm = MagicMock()
    llm.chat_stream = fake_chat_stream

    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value={
        "ok": True, "found": True,
        "chunks": [{"doc_id": "d1", "filename": "x.pdf", "page_no": 12,
                     "snippet": "营收 6605 亿…", "score": 0.85}]
    })

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=89,
                  status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()
    mem.save_tool_message = AsyncMock()

    engine = ConversationEngine(mem=mem, llm=llm, tools=tools, persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="问")]

    cit = next(e for e in events if e.type == "citations")
    assert len(cit.data["chunks"]) == 1
    assert cit.data["chunks"][0]["page_no"] == 12

@pytest.mark.asyncio
async def test_template_a_with_tool_found_false_emits_empty_citations():
    """Tool returns found=false → citations event with chunks=[]."""
    from unittest.mock import AsyncMock, MagicMock

    class _LLMChunk:
        def __init__(self, text_delta="", tool_call_deltas=None, finish_reason=None):
            self.text_delta = text_delta
            self.tool_call_deltas = tool_call_deltas or []
            self.finish_reason = finish_reason

    class _ToolDelta:
        def __init__(self, id, name=None, arguments=None):
            self.id, self.name, self.arguments = id, name, arguments

    async def fake_chat_stream(messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            yield _LLMChunk(tool_call_deltas=[_ToolDelta(
                id="t1", name="search_documents", arguments='{"query":"x"}')])
            yield _LLMChunk(finish_reason="tool_calls")
        else:
            yield _LLMChunk(text_delta="在已上传文档中未找到相关信息。")
            yield _LLMChunk(finish_reason="stop")

    llm = MagicMock(); llm.chat_stream = fake_chat_stream
    tools = MagicMock()
    tools.schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value={"ok": True, "found": False, "chunks": []})

    mem = MagicMock()
    mem.count_documents_by_status = AsyncMock(return_value={"ready": 1, "processing": 0, "failed": 0})
    mem.list_documents = AsyncMock(return_value=[
        MagicMock(filename="x.pdf", page_count=89, status=MagicMock(value="ready"))
    ])
    mem.list_messages = AsyncMock(return_value=[])
    mem.save_user_message = AsyncMock()
    mem.save_assistant_message = AsyncMock()

    engine = ConversationEngine(mem=mem, llm=llm, tools=tools, persona="助手")
    events = [e async for e in engine.handle_stream(session_id="sid", message="问")]
    cit = next(e for e in events if e.type == "citations")
    assert cit.data["chunks"] == []
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/test_conversation_engine.py -v
```
Expected: ImportError or fixture errors.

- [ ] **Step 3: Implement engine**

Replace `src/core/conversation_engine.py`:

```python
"""Spec §6 + §7: 4-template dispatch + structured citations binding."""
import json
import logging
from typing import AsyncIterator

from src.api.sse import StreamEvent
from src.core.prompt_templates import (
    FIXED_RESPONSES, render_system_prompt, select_template,
)

log = logging.getLogger(__name__)


class ConversationEngine:
    def __init__(self, *, mem, llm, tools, persona: str):
        self.mem = mem
        self.llm = llm
        self.tools = tools
        self.persona = persona

    async def handle_stream(self, *, session_id, message: str) -> AsyncIterator[StreamEvent]:
        # Persist user message immediately
        await self.mem.save_user_message(session_id, message)

        counts = await self.mem.count_documents_by_status(session_id)
        template = select_template(counts)

        if template != "A":
            fixed = FIXED_RESPONSES[template]
            # Stream the fixed text in one delta (could chunk by char if desired)
            yield StreamEvent.text(delta=fixed)
            yield StreamEvent.citations(chunks=[])
            await self.mem.save_assistant_message(session_id, fixed, citations=[])
            yield StreamEvent.done()
            return

        # Template A
        docs = await self.mem.list_documents(session_id)
        ready_docs = [
            {"filename": d.filename, "page_count": d.page_count}
            for d in docs
            if (d.status.value if hasattr(d.status, "value") else d.status) == "ready"
        ]
        system_prompt = render_system_prompt("A", docs=ready_docs, persona=self.persona)

        history = [{"role": m.role.value if hasattr(m.role, "value") else m.role,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id}
                   for m in await self.mem.list_messages(session_id)]
        messages = [{"role": "system", "content": system_prompt}] + history

        collected_chunks: list[dict] = []
        all_found_false = True
        had_any_tool_call = False
        final_text_buf = ""

        # Tool-calling loop, max 5 iterations
        for _ in range(5):
            text_buf = ""
            tool_call_acc = {}  # id -> {name, arguments_str}
            finish_reason = None

            async for chunk in self.llm.chat_stream(messages, tools=self.tools.schemas()):
                if chunk.text_delta:
                    text_buf += chunk.text_delta
                    yield StreamEvent.text(delta=chunk.text_delta)
                for d in chunk.tool_call_deltas or []:
                    acc = tool_call_acc.setdefault(d.id, {"name": d.name or "", "arguments": ""})
                    if d.name:
                        acc["name"] = d.name
                    if d.arguments:
                        acc["arguments"] += d.arguments
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

            if finish_reason == "stop":
                final_text_buf = text_buf
                messages.append({"role": "assistant", "content": text_buf})
                break

            if finish_reason == "tool_calls" and tool_call_acc:
                had_any_tool_call = True
                # Persist assistant turn with tool_calls structure
                tc_list = [
                    {"id": tid, "type": "function",
                     "function": {"name": acc["name"], "arguments": acc["arguments"]}}
                    for tid, acc in tool_call_acc.items()
                ]
                messages.append({"role": "assistant", "content": text_buf,
                                  "tool_calls": tc_list})

                for tid, acc in tool_call_acc.items():
                    yield StreamEvent.tool_call_started(id=tid, name=acc["name"])
                    try:
                        args = json.loads(acc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await self.tools.execute(acc["name"], args, session_id=session_id)
                    if acc["name"] == "search_documents" and result.get("ok"):
                        if result.get("found"):
                            all_found_false = False
                            collected_chunks.extend(result.get("chunks", []))
                    yield StreamEvent.tool_call_finished(id=tid, ok=bool(result.get("ok")))

                    messages.append({
                        "role": "tool", "tool_call_id": tid,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                continue

            # finish_reason missing or other → break to avoid loop
            break

        # Citations decision (spec §7 structured signal)
        if not had_any_tool_call or all_found_false:
            citations: list[dict] = []
        else:
            # Strip 'content' from chunks for SSE/persistence; keep snippet/score/etc.
            citations = [
                {k: v for k, v in c.items() if k != "content"}
                for c in collected_chunks
            ]

        # De-dupe citations on (doc_id, page_no)
        seen = set()
        unique_citations = []
        for c in citations:
            key = (c["doc_id"], c["page_no"])
            if key in seen:
                continue
            seen.add(key)
            unique_citations.append(c)

        await self.mem.save_assistant_message(
            session_id, final_text_buf, citations=unique_citations,
        )
        yield StreamEvent.citations(chunks=unique_citations)
        yield StreamEvent.done()
```

- [ ] **Step 4: Verify B-* tests pass**

```bash
uv run pytest tests/unit/test_conversation_engine.py -v -k "b_empty or b_processing"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/conversation_engine.py tests/unit/test_conversation_engine.py
git commit -m "feat(engine): 4-template dispatch + structured citations binding"
```

---

## Task 13: Wire ConversationEngine + Tool Registry into Chat API

**Goal:** Update `src/api/chat.py` to use the new tool registry + engine. Ensure `POST /chat/stream` emits `citations` events.

**Files:**
- Modify: `src/api/chat.py`
- Modify: `src/main.py` (deps wiring)

- [ ] **Step 1: Update deps in main.py**

In `make_app_default()`, replace the existing tool/engine wiring:

```python
from src.core.tool_registry import ToolRegistry
from src.embedding.bge_embedder import BgeEmbedder

bge = BgeEmbedder()
deps["embedder"] = bge

cfg = get_config()
min_sim = float(os.environ.get("MIN_SIMILARITY", cfg["retrieval"]["min_similarity"]))
top_k = int(cfg["retrieval"]["top_k"])
deps["min_similarity"] = min_sim
deps["top_k"] = top_k
```

(Tool registry is created per-request inside `_build_engine` because it depends on `mem`.)

- [ ] **Step 2: Update chat.py engine factory**

Find the existing `_build_engine(db)` (or equivalent) in `src/api/chat.py` and replace its body with:

```python
def _build_engine(db: AsyncSession):
    mem = MemoryService(db)
    tools = ToolRegistry(
        mem=mem, embedder=deps["embedder"],
        min_similarity=deps["min_similarity"], top_k=deps["top_k"],
    )
    persona = persona_loader.load()
    return ConversationEngine(mem=mem, llm=deps["llm"], tools=tools, persona=persona)
```

- [ ] **Step 3: Smoke test the chat endpoint**

```bash
uv run pytest tests/unit/test_api_*.py -v -k "not delete and not memory"
```
Expected: existing chat tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/main.py src/api/chat.py
git commit -m "feat(api): wire new engine + tool registry into chat router"
```

---

## Task 14: Calibration Script

**Goal:** Implement `scripts/calibrate_threshold.py` per spec §13 T2.5. Stdout report only — no config writes.

**Files:**
- Create: `scripts/calibrate_threshold.py`

- [ ] **Step 1: Implement script**

Create `scripts/calibrate_threshold.py`:

```python
#!/usr/bin/env python3
"""Threshold calibration. Spec §5/§13 T2.5.

Usage:
  python scripts/calibrate_threshold.py <session_id_with_ready_doc>

Prints per-query top-K similarity scores and a suggested MIN_SIMILARITY value.
DOES NOT modify config. Copy the suggested value to .env if desired.
"""
import asyncio
import sys
from statistics import mean

RELEVANT_QUERIES = ["总营收", "业务板块", "风险因素"]
IRRELEVANT_QUERIES = ["今天天气如何", "梅西踢哪个俱乐部", "如何做红烧肉"]
TOP_K = 8


async def main(session_id: str):
    from src.db.session import get_sessionmaker
    from src.core.memory_service import MemoryService
    from src.embedding.bge_embedder import BgeEmbedder

    embedder = BgeEmbedder()
    Sessionmaker = get_sessionmaker()
    relevant_min = []
    irrelevant_max = []

    async with Sessionmaker() as db:
        mem = MemoryService(db)
        for label, queries, accumulator in [
            ("RELEVANT", RELEVANT_QUERIES, relevant_min),
            ("IRRELEVANT", IRRELEVANT_QUERIES, irrelevant_max),
        ]:
            print(f"\n=== {label} ===")
            for q in queries:
                emb = embedder.encode_one(q)
                hits = await mem.search_chunks(
                    session_id, query_embedding=list(emb),
                    top_k=TOP_K, min_similarity=0.0,
                )
                scores = [h["score"] for h in hits]
                print(f"  query={q!r:<30} top-{TOP_K} scores={[f'{s:.3f}' for s in scores]}")
                if label == "RELEVANT" and scores:
                    accumulator.append(min(scores[: max(1, TOP_K // 2)]))
                if label == "IRRELEVANT" and scores:
                    accumulator.append(max(scores))

    if relevant_min and irrelevant_max:
        suggested = round((mean(relevant_min) + mean(irrelevant_max)) / 2, 2)
        print(f"\nRelevant lower-bound (avg mid-top): {mean(relevant_min):.3f}")
        print(f"Irrelevant upper-bound (avg max):    {mean(irrelevant_max):.3f}")
        print(f"\nSuggested MIN_SIMILARITY = {suggested}")
        print(f"Add to .env (optional):  MIN_SIMILARITY={suggested}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 2: Verify script runs (manual)**

```bash
chmod +x scripts/calibrate_threshold.py
# After Tencent annual report is uploaded into a session:
# uv run python scripts/calibrate_threshold.py <session_id>
```

- [ ] **Step 3: Commit**

```bash
git add scripts/calibrate_threshold.py
git commit -m "feat(scripts): threshold calibration (stdout report, no config write)"
```

---

## Task 15: Backend E2E (4 question types + 4 no-answer states)

**Goal:** Spec §10 E2E. Use Tencent annual report fixture. Real Moonshot calls (marked `@pytest.mark.llm`).

**Files:**
- Create: `tests/e2e/test_doc_qa.py`
- Place fixture: `tests/fixtures/example/腾讯2025年度报告.pdf` (user-provided)

- [ ] **Step 1: Add the example PDF**

User must place `tests/fixtures/example/腾讯2025年度报告.pdf` (the file shipped with the challenge). Verify:

```bash
ls -lh tests/fixtures/example/腾讯2025年度报告.pdf
```

- [ ] **Step 2: Write E2E**

Create `tests/e2e/test_doc_qa.py`:

```python
"""E2E: real LLM, real BGE, real DB. Marked @pytest.mark.llm — skipped by default.

Run with: pytest -m llm tests/e2e/test_doc_qa.py -v
"""
import asyncio
import json
from pathlib import Path
import pytest
from httpx import AsyncClient
from src.main import make_app_default

PDF = Path(__file__).parent.parent / "fixtures" / "example" / "腾讯2025年度报告.pdf"

pytestmark = pytest.mark.llm


@pytest.fixture
async def client_with_doc():
    app = make_app_default()
    async with AsyncClient(app=app, base_url="http://test", timeout=600) as c:
        sid = (await c.post("/sessions")).json()["session_id"]
        files = {"file": ("腾讯2025年度报告.pdf", PDF.read_bytes(), "application/pdf")}
        r = await c.post(f"/sessions/{sid}/documents", files=files)
        doc_id = r.json()["document_id"]
        # Wait for ready (max ~120s)
        for _ in range(240):
            docs = (await c.get(f"/sessions/{sid}/documents")).json()
            if docs and docs[0]["status"] == "ready":
                break
            if docs and docs[0]["status"] == "failed":
                pytest.fail(f"ingestion failed: {docs[0]['error_message']}")
            await asyncio.sleep(0.5)
        else:
            pytest.fail("ingestion timeout")
        yield c, sid


async def _ask_collect(client, sid, q):
    """POST /chat/stream and collect (full_text, citations)."""
    async with client.stream("POST", "/chat/stream",
                              json={"session_id": sid, "message": q}) as resp:
        text = ""
        cits = []
        block = ""
        async for chunk in resp.aiter_text():
            block += chunk
            while "\n\n" in block:
                frame, block = block.split("\n\n", 1)
                event = None
                data_str = ""
                for line in frame.split("\n"):
                    if line.startswith("event: "): event = line[7:]
                    elif line.startswith("data: "): data_str += line[6:]
                if not event: continue
                data = json.loads(data_str) if data_str else {}
                if event == "text": text += data.get("delta", "")
                elif event == "citations": cits = data.get("chunks", [])
                elif event == "done": return text, cits
    return text, cits


@pytest.mark.asyncio
async def test_factual_query_returns_answer_with_citation(client_with_doc):
    client, sid = client_with_doc
    text, cits = await _ask_collect(client, sid, "腾讯 2025 年总营业收入是多少？")
    assert any(s in text for s in ["6,605", "6605", "六千"]), f"answer: {text}"
    assert len(cits) >= 1
    assert all(c.get("page_no") for c in cits)

@pytest.mark.asyncio
async def test_summary_query_returns_multiple_citations(client_with_doc):
    client, sid = client_with_doc
    text, cits = await _ask_collect(client, sid, "请总结主要业务板块")
    assert len(text) > 20
    assert len(cits) >= 1   # ≥3 ideal but model-dependent

@pytest.mark.asyncio
async def test_comparison_query(client_with_doc):
    client, sid = client_with_doc
    text, _ = await _ask_collect(client, sid, "2025 年净利润相比 2024 年增长了多少？")
    # Model may either compute or say "未找到"; both are acceptable per spec
    # provided no fabrication occurs. We assert one of the two.
    assert ("未找到相关信息" in text) or any(d.isdigit() for d in text)

@pytest.mark.asyncio
async def test_out_of_scope_query_says_not_found(client_with_doc):
    client, sid = client_with_doc
    text, cits = await _ask_collect(client, sid, "今天天气如何？")
    assert "未找到相关信息" in text
    assert cits == []

@pytest.mark.asyncio
async def test_b_empty_no_documents_uploaded():
    app = make_app_default()
    async with AsyncClient(app=app, base_url="http://test", timeout=60) as c:
        sid = (await c.post("/sessions")).json()["session_id"]
        text, cits = await _ask_collect(c, sid, "随便问个问题")
        assert "请先上传" in text
        assert cits == []
```

- [ ] **Step 3: Run E2E**

```bash
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/chat \
  uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat \
  MOONSHOT_API_KEY=$MOONSHOT_API_KEY \
  uv run pytest -m llm tests/e2e/test_doc_qa.py -v --timeout=600
```
Expected: 5 PASS (ingestion takes ~60s once, then queries are fast).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_doc_qa.py tests/fixtures/example/.gitkeep
git commit -m "test(e2e): doc QA covering factual/summary/comparison/no-answer"
```

(Note: do NOT commit the PDF if it's a copyrighted artifact. Add `tests/fixtures/example/*.pdf` to .gitignore and document in README that user must place the file manually.)

---

## Task 16: Frontend Types + SSE Parser Update

**Goal:** Extend `types.ts` with `Document`, `Citation`, and `Message.citations`. Update SSE parser to handle `citations` event.

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/sse-stream.ts`
- Modify: `frontend/tests/sse-stream.test.ts`

- [ ] **Step 1: Failing test for citations event parsing**

Append to `frontend/tests/sse-stream.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { parseSSE } from '../lib/sse-stream';

describe('citations event', () => {
  it('parses citations event', async () => {
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(
          'event: citations\ndata: {"chunks":[{"doc_id":"d1","filename":"x.pdf","page_no":12,"snippet":"s","score":0.8}]}\n\n'
        ));
        c.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'));
        c.close();
      }
    });
    const events: any[] = [];
    for await (const ev of parseSSE(stream)) events.push(ev);
    const cit = events.find(e => e.type === 'citations');
    expect(cit).toBeDefined();
    expect(cit.chunks[0].page_no).toBe(12);
  });

  it('parses empty citations event', async () => {
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode('event: citations\ndata: {"chunks":[]}\n\n'));
        c.close();
      }
    });
    const events: any[] = [];
    for await (const ev of parseSSE(stream)) events.push(ev);
    expect(events[0].chunks).toEqual([]);
  });
});
```

- [ ] **Step 2: Verify failure**

```bash
cd frontend && pnpm vitest run tests/sse-stream.test.ts
```
Expected: FAIL on `citations` event type.

- [ ] **Step 3: Update types**

Edit `frontend/lib/types.ts`:

```typescript
export type Citation = {
  doc_id: string;
  filename: string;
  page_no: number;
  snippet: string;
  score: number;
};

export type Document = {
  document_id: string;
  filename: string;
  page_count: number;
  progress_page: number;
  status: 'processing' | 'ready' | 'failed';
  error_message?: string | null;
  uploaded_at?: string | null;
};

export type ToolStatus = 'running' | 'ok' | 'error';
export type ToolChip = { id: string; name: string; status: ToolStatus };

export type Message = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tools?: ToolChip[];
  citations?: Citation[];
};

export type ServerEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_call_started'; id: string; name: string }
  | { type: 'tool_call_finished'; id: string; ok: boolean }
  | { type: 'citations'; chunks: Citation[] }
  | { type: 'done' }
  | { type: 'error'; message: string; code?: string };
```

- [ ] **Step 4: Update SSE parser**

Edit `frontend/lib/sse-stream.ts`. Find the event-type switch and add a `citations` case (whatever existing structure is — typically just spreading `data` into the discriminated union):

```typescript
// In the type-discrimination block:
if (event === 'citations') {
  yield { type: 'citations', chunks: data.chunks ?? [] };
  continue;
}
```

- [ ] **Step 5: Verify**

```bash
cd frontend && pnpm vitest run tests/sse-stream.test.ts
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/sse-stream.ts frontend/tests/sse-stream.test.ts
git commit -m "feat(frontend): add Citation/Document types + citations SSE event"
```

---

## Task 17: Frontend API Client (uploadDocument, listDocuments, deleteDocument)

**Goal:** Add three new HTTP methods to `lib/api.ts`. Use `FormData` for upload.

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Implement**

Append to `frontend/lib/api.ts`:

```typescript
import type { Document } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

export async function uploadDocument(
  sessionId: string, file: File
): Promise<Document> {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/documents`, {
    method: 'POST', body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Upload failed: ${r.status}`);
  }
  return r.json();
}

export async function listDocuments(sessionId: string): Promise<Document[]> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/documents`);
  if (!r.ok) throw new Error(`List failed: ${r.status}`);
  return r.json();
}

export async function deleteDocument(
  sessionId: string, documentId: string
): Promise<void> {
  const r = await fetch(
    `${API_BASE}/sessions/${sessionId}/documents/${documentId}`,
    { method: 'DELETE' }
  );
  if (r.status === 409) throw new Error('正在解析中，请稍后再删除');
  if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
}

export function progressUrl(sessionId: string, documentId: string): string {
  return `${API_BASE}/sessions/${sessionId}/documents/${documentId}/progress`;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(frontend): API client for document upload/list/delete + progress URL"
```

---

## Task 18: Frontend Hooks — `useDocuments` + `useDocumentProgress`

**Goal:** Two hooks: list-and-poll + per-document SSE progress.

**Files:**
- Create: `frontend/lib/use-documents.ts`
- Create: `frontend/lib/use-document-progress.ts`

- [ ] **Step 1: Implement `useDocuments`**

Create `frontend/lib/use-documents.ts`:

```typescript
import { useCallback, useEffect, useState } from 'react';
import { listDocuments } from './api';
import type { Document } from './types';

export function useDocuments(sessionId: string) {
  const [docs, setDocs] = useState<Document[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments(sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [sessionId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Poll while any doc is processing
  useEffect(() => {
    const anyProcessing = docs.some(d => d.status === 'processing');
    if (!anyProcessing) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [docs, refresh]);

  return { docs, error, refresh, setDocs };
}
```

- [ ] **Step 2: Implement `useDocumentProgress`**

Create `frontend/lib/use-document-progress.ts`:

```typescript
import { useEffect, useState } from 'react';
import { progressUrl } from './api';

export type Progress = {
  page: number; total: number; phase: string;
} | { status: 'ready' | 'failed'; error?: string | null };

export function useDocumentProgress(
  sessionId: string, documentId: string, enabled: boolean,
): Progress | null {
  const [progress, setProgress] = useState<Progress | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(progressUrl(sessionId, documentId));
    es.addEventListener('progress', (e: MessageEvent) => {
      setProgress(JSON.parse(e.data));
    });
    es.addEventListener('done', (e: MessageEvent) => {
      setProgress(JSON.parse(e.data));
      es.close();
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [sessionId, documentId, enabled]);
  return progress;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/use-documents.ts frontend/lib/use-document-progress.ts
git commit -m "feat(frontend): useDocuments + useDocumentProgress hooks"
```

---

## Task 19: Extend `useChatStream` for citations

**Goal:** Handle `citations` event by attaching to the latest assistant message.

**Files:**
- Modify: `frontend/lib/use-chat-stream.ts`

- [ ] **Step 1: Update applyEvent**

Find `applyEvent` in `frontend/lib/use-chat-stream.ts`. Add a `citations` branch:

```typescript
if (ev.type === 'citations') {
  return prev.map((m, i) =>
    i === prev.length - 1 && m.role === 'assistant'
      ? { ...m, citations: ev.chunks }
      : m
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/use-chat-stream.ts
git commit -m "feat(frontend): bind citations event to assistant message"
```

---

## Task 20: `<DocumentUploadHero>` (empty-state)

**Goal:** Spec §8.2 — full-bleed hero with title/subtitle + dashed dropzone. Drag-and-drop + click-to-select.

**Files:**
- Create: `frontend/components/document-upload-hero.tsx`

- [ ] **Step 1: Implement**

Create `frontend/components/document-upload-hero.tsx`:

```tsx
"use client";
import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";

type Props = {
  sessionId: string;
  onUploaded: () => void;
};

export function DocumentUploadHero({ sessionId, onUploaded }: Props) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onUploaded();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="flex h-full flex-col items-center justify-center p-8 gap-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold mb-2">📄 文档问答</h1>
        <p className="text-sm text-muted-foreground max-w-md">
          上传 PDF，针对内容自由提问。所有回答都附带原文出处。
        </p>
      </div>

      <div
        className={`w-full max-w-lg cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition ${
          dragging ? "border-indigo-400 bg-indigo-50" : "border-gray-300 hover:bg-gray-50"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) upload(file);
        }}
      >
        <div className="text-3xl mb-2">📥</div>
        <div className="font-medium text-gray-700 mb-1">
          {dragging ? "松开以上传 PDF" : "拖入 PDF 或点击上传"}
        </div>
        <div className="text-xs text-gray-500">支持中文 · ≤20MB · 可上传多份</div>
        <input ref={inputRef} type="file" accept=".pdf" hidden
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); }} />
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/document-upload-hero.tsx
git commit -m "feat(frontend): empty-state hero with drag-and-drop upload"
```

---

## Task 21: `<DocumentTopBar>` + `<DocumentRow>`

**Goal:** Spec §8.3 — horizontal bar with 3-state rows + delete button + small upload-more button.

**Files:**
- Create: `frontend/components/document-row.tsx`
- Create: `frontend/components/document-top-bar.tsx`

- [ ] **Step 1: Implement DocumentRow**

Create `frontend/components/document-row.tsx`:

```tsx
"use client";
import { X } from "lucide-react";
import type { Document } from "@/lib/types";
import { useDocumentProgress } from "@/lib/use-document-progress";

type Props = {
  sessionId: string;
  doc: Document;
  onDelete: (docId: string) => void;
};

export function DocumentRow({ sessionId, doc, onDelete }: Props) {
  const progress = useDocumentProgress(sessionId, doc.document_id,
                                        doc.status === 'processing');

  if (doc.status === 'processing') {
    const page = (progress as any)?.page ?? doc.progress_page ?? 0;
    const total = doc.page_count;
    const pct = total ? Math.round((page / total) * 100) : 0;
    return (
      <div className="rounded border border-amber-200 bg-amber-50 p-2 min-w-[260px]">
        <div className="flex items-center gap-2">
          <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
          <span className="text-xs flex-1 truncate">{doc.filename}</span>
          <span className="rounded-full bg-amber-200 text-amber-900 text-[10px] px-2 py-0.5">解析中</span>
        </div>
        <div className="h-1 bg-amber-100 rounded mt-1 overflow-hidden">
          <div className="h-full bg-amber-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="text-[10px] text-amber-800 mt-1">
          正在向量化第 {page} / {total} 页…
        </div>
      </div>
    );
  }

  if (doc.status === 'ready') {
    return (
      <div className="rounded border border-green-200 bg-green-50 p-2 flex items-center gap-2 min-w-[200px]">
        <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
        <span className="text-xs flex-1 truncate">{doc.filename}</span>
        <span className="text-[10px] text-gray-500">{doc.page_count}页</span>
        <span className="rounded-full bg-green-200 text-green-900 text-[10px] px-2 py-0.5">✓ 就绪</span>
        <button onClick={() => onDelete(doc.document_id)}
                className="text-gray-400 hover:text-gray-600">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  // failed
  return (
    <div className="rounded border border-red-200 bg-red-50 p-2 min-w-[260px]">
      <div className="flex items-center gap-2">
        <span className="rounded bg-red-600 text-white text-[10px] font-bold px-1.5 py-0.5">PDF</span>
        <span className="text-xs flex-1 truncate">{doc.filename}</span>
        <span className="rounded-full bg-red-200 text-red-900 text-[10px] px-2 py-0.5">✗ 失败</span>
        <button onClick={() => onDelete(doc.document_id)}
                className="text-gray-400 hover:text-gray-600">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {doc.error_message && (
        <div className="text-[10px] text-red-700 mt-1">{doc.error_message}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement DocumentTopBar**

Create `frontend/components/document-top-bar.tsx`:

```tsx
"use client";
import { useRef, useState } from "react";
import type { Document } from "@/lib/types";
import { uploadDocument, deleteDocument } from "@/lib/api";
import { DocumentRow } from "./document-row";

type Props = {
  sessionId: string;
  docs: Document[];
  onChange: () => void;
};

export function DocumentTopBar({ sessionId, docs, onChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setError(null);
    try {
      await uploadDocument(sessionId, file);
      onChange();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleDelete(docId: string) {
    setError(null);
    try {
      await deleteDocument(sessionId, docId);
      onChange();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="border-b bg-gray-50 p-2">
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-[10px] uppercase font-semibold text-gray-500">文档</span>
        {docs.map(d => (
          <DocumentRow key={d.document_id} sessionId={sessionId} doc={d} onDelete={handleDelete} />
        ))}
        <button onClick={() => inputRef.current?.click()}
                className="rounded border border-dashed border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-white">
          + 添加
        </button>
        <input ref={inputRef} type="file" accept=".pdf" hidden
          onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
      </div>
      {error && <div className="text-xs text-red-600 mt-1">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/document-row.tsx frontend/components/document-top-bar.tsx
git commit -m "feat(frontend): document top bar + 3-state rows + delete button"
```

---

## Task 22: `<CitationCard>`

**Goal:** Spec §8.4 — red PDF badge + filename + page badge + 2-line snippet, click to expand.

**Files:**
- Create: `frontend/components/citation-card.tsx`
- Test: `frontend/tests/citation-card.test.tsx`

- [ ] **Step 1: Failing test**

Create `frontend/tests/citation-card.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { CitationCard } from '../components/citation-card';

describe('CitationCard', () => {
  it('renders filename and page badge', () => {
    const { getByText } = render(
      <CitationCard citations={[{
        doc_id: 'a', filename: '腾讯2025.pdf', page_no: 12,
        snippet: '一段 snippet', score: 0.8,
      }]} />
    );
    expect(getByText('腾讯2025.pdf')).toBeTruthy();
    expect(getByText(/p\.12|第 12 页/)).toBeTruthy();
  });

  it('shows count for multiple sources', () => {
    const { getByText } = render(
      <CitationCard citations={[
        { doc_id: 'a', filename: 'x.pdf', page_no: 1, snippet: 's', score: 0.8 },
        { doc_id: 'a', filename: 'x.pdf', page_no: 2, snippet: 's', score: 0.7 },
      ]} />
    );
    expect(getByText(/来源（2）/)).toBeTruthy();
  });

  it('renders nothing when citations empty', () => {
    const { container } = render(<CitationCard citations={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Verify failure**

```bash
cd frontend && pnpm vitest run tests/citation-card.test.tsx
```

- [ ] **Step 3: Implement**

Create `frontend/components/citation-card.tsx`:

```tsx
"use client";
import { useState } from "react";
import type { Citation } from "@/lib/types";

type Props = { citations: Citation[] };

export function CitationCard({ citations }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  if (!citations || citations.length === 0) return null;

  function toggle(i: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  }

  return (
    <div className="mt-3 pt-3 border-t border-gray-200">
      <div className="text-[11px] font-semibold uppercase text-gray-500 mb-2">
        📚 来源（{citations.length}）
      </div>
      <div className="flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <div key={i}
               onClick={() => toggle(i)}
               className="flex items-start gap-2.5 rounded-md border bg-gray-50 p-2.5 cursor-pointer hover:bg-gray-100">
            <span className="rounded bg-red-500 text-white text-[10px] font-bold px-1.5 py-1">PDF</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-gray-800">{c.filename}</div>
              <div className={`text-[11px] text-gray-600 mt-0.5 ${expanded.has(i) ? '' : 'line-clamp-2'}`}>
                {c.snippet}
              </div>
            </div>
            <span className="rounded bg-indigo-100 text-indigo-800 text-[10px] font-semibold px-1.5 py-0.5 shrink-0">
              p.{c.page_no}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd frontend && pnpm vitest run tests/citation-card.test.tsx
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/citation-card.tsx frontend/tests/citation-card.test.tsx
git commit -m "feat(frontend): CitationCard with expand-on-click"
```

---

## Task 23: Integrate everything into `<ChatPane>` (D layout)

**Goal:** Wire the new components into the chat pane: empty-state hero (when no docs) ↔ top bar (when ≥1 doc); citations rendered in MessageBubble; input disabled until ≥1 ready doc.

**Files:**
- Modify: `frontend/components/chat-pane.tsx`
- Modify: `frontend/components/message-bubble.tsx`

- [ ] **Step 1: Update MessageBubble**

Edit `frontend/components/message-bubble.tsx`. After the existing content rendering, add:

```tsx
import { CitationCard } from "./citation-card";

// inside the assistant branch, after rendering content + tool chips:
{message.role === 'assistant' && message.citations && (
  <CitationCard citations={message.citations} />
)}
```

- [ ] **Step 2: Rewrite ChatPane**

Replace `frontend/components/chat-pane.tsx`:

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { listMessages } from "@/lib/api";
import { useChatStream } from "@/lib/use-chat-stream";
import { useDocuments } from "@/lib/use-documents";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./message-bubble";
import { DocumentUploadHero } from "./document-upload-hero";
import { DocumentTopBar } from "./document-top-bar";

type Props = {
  sessionId: string;
  onFirstMessageSent: () => void;
};

export function ChatPane({ sessionId, onFirstMessageSent }: Props) {
  const { docs, refresh: refreshDocs } = useDocuments(sessionId);
  const { messages, streaming, error, send, setMessages } =
    useChatStream(sessionId);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load history on session change — preserve optimistic messages
  useEffect(() => {
    let cancelled = false;
    listMessages(sessionId).then(hist => {
      if (cancelled) return;
      const converted = hist.map((m: any, idx: number) => ({
        id: `hist-${idx}`,
        role: m.role,
        content: m.content,
        citations: m.citations ?? undefined,
      }));
      setMessages(prev => prev.length === 0 ? converted : prev);
    });
    return () => { cancelled = true; };
  }, [sessionId, setMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const hasReady = docs.some(d => d.status === 'ready');
  const hasAny = docs.length > 0;
  const inputDisabled = streaming || !hasReady;

  async function handleSend() {
    if (!input.trim() || inputDisabled) return;
    const text = input;
    setInput("");
    const wasFirst = messages.length === 0;
    await send(text);
    if (wasFirst) onFirstMessageSent();
  }

  if (!hasAny) {
    return (
      <DocumentUploadHero sessionId={sessionId} onUploaded={refreshDocs} />
    );
  }

  return (
    <div className="flex flex-col h-full">
      <DocumentTopBar sessionId={sessionId} docs={docs} onChange={refreshDocs} />
      <ScrollArea className="flex-1 p-4">
        <div className="flex flex-col gap-3">
          {messages.map(m => <MessageBubble key={m.id} message={m} />)}
          {error && (
            <div className="text-sm text-orange-600">
              {error.message} <button onClick={() => send(error.lastUserMessage)}>重试</button>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
      <div className="p-4 border-t bg-white flex gap-2">
        <Textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault(); handleSend();
            }
          }}
          placeholder={hasReady ? "输入问题…" : "请等待文档解析完成…"}
          disabled={inputDisabled}
          rows={1}
        />
        <Button onClick={handleSend} disabled={inputDisabled || !input.trim()}>
          发送
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Manual smoke test**

```bash
docker compose up -d postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat \
  MOONSHOT_API_KEY=$MOONSHOT_API_KEY \
  uv run uvicorn --factory src.main:make_app_default --reload &
cd frontend && pnpm dev
```

Open http://localhost:3000 — verify: empty state shows hero, upload PDF, see processing → ready, ask question, see answer with citation cards.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/chat-pane.tsx frontend/components/message-bubble.tsx
git commit -m "feat(frontend): D-layout integration (empty hero ↔ top bar) + citations rendered"
```

---

## Task 24: Persona Rewrite

**Goal:** Replace stub `persona/IDENTITY.md` and `persona/SOUL.md` with document-QA-assistant identity. No insurance / 保险经纪 references.

**Files:**
- Replace: `persona/IDENTITY.md`
- Replace: `persona/SOUL.md`

- [ ] **Step 1: Write IDENTITY.md**

```markdown
# 助手身份

你是一个**文档问答助手**。用户上传 PDF 文档，你基于这些文档的内容回答问题，并附带页码出处。

## 核心边界
- 你**只**能基于用户当前会话已上传的 PDF 内容作答
- 你**不能**调用常识、训练知识或外部信息补充答案
- 检索到的内容不相关时，你必须如实告知"在已上传文档中未找到相关信息"
- 你**不**生成、续写、翻译、改写文档之外的内容

## 语气
- 简洁、专业、中立
- 不寒暄，不解释为什么没找到答案
- 数字保持文档中的原始精度（如 6,605 亿元，不要四舍五入）
```

- [ ] **Step 2: Write SOUL.md**

```markdown
# 行为准则

1. **只检索一次再答**：先调用 `search_documents` 工具检索；基于工具返回再答
2. **找不到就说找不到**：工具返回 `found=false` 或 `chunks=[]` 时，**完整、原样**回答："在已上传文档中未找到相关信息。" 不要补充猜测
3. **不标内联引用**：不要在回答中写 [1] [2] 之类标注；前端会自动渲染来源卡片
4. **纯文本输出**：不要使用 Markdown 格式（不要 `**` `# ` `\`\`\`` 等）
5. **数字保留精度**：报告中的数字原样输出，不四舍五入、不换算单位
```

- [ ] **Step 3: Verify persona_loader still loads**

```bash
uv run pytest tests/unit/test_persona_loader.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add persona/IDENTITY.md persona/SOUL.md
git commit -m "feat(persona): rewrite as document QA assistant"
```

---

## Task 25: Docker Volume + Bootstrap Update

**Goal:** Persist `data/uploads/` across container restarts. Ensure `.tmp` exists.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `scripts/bootstrap.sh`

- [ ] **Step 1: Add data volume to docker-compose.yml**

Edit `docker-compose.yml`. In the `backend` service block, under `volumes:`, add:

```yaml
      - ./data/uploads:/app/data/uploads
```

If a `volumes:` block doesn't exist for backend, create it with that single entry plus existing bind mounts (e.g., source code mount in dev mode).

- [ ] **Step 2: Ensure dirs exist on container start**

Edit `Dockerfile` (backend). Before the `CMD`, add:

```dockerfile
RUN mkdir -p /app/data/uploads/.tmp
```

- [ ] **Step 3: Update bootstrap.sh**

Edit `scripts/bootstrap.sh`. After the `docker compose up -d postgres` line, add:

```bash
mkdir -p data/uploads/.tmp
```

- [ ] **Step 4: Smoke test the docker stack**

```bash
docker compose down -v
docker compose up --build -d
sleep 10
curl -s http://localhost:8000/sessions -X POST | jq
docker compose logs backend | tail -20
```
Expected: 200 response from `/sessions`. Logs show startup hook ran (`cleanup_stale_documents`).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml Dockerfile scripts/bootstrap.sh
git commit -m "chore(docker): mount data/uploads volume + ensure .tmp exists"
```

---

## Task 26: README + Screenshots

**Goal:** Spec §12 README plus 6 verification screenshots.

**Files:**
- Create: `README.md`
- Create: `docs/screenshots/*.png`

- [ ] **Step 1: Write README.md**

Create `README.md` (replace stub if exists):

```markdown
# 文档问答助手 (Document QA Assistant)

针对 PDF 文档的中文问答聊天机器人。所有回答都基于上传文档的内容，并附带页码出处。

## 一键启动

```bash
cp .env.example .env       # 填入 MOONSHOT_API_KEY
docker compose up
```

> 首次启动约 5–10 分钟（下载 BGE-large-zh-v1.5 模型 ~1GB）。后续启动秒级。

打开 http://localhost:3000，点击「新对话」，拖入 PDF 开始提问。

## 配置

环境变量：
- `MOONSHOT_API_KEY` （必填）— 硅基流动 API key
- `MIN_SIMILARITY` （可选，默认 0.35）— 检索相关性阈值
  - default 0.35 基于本仓库附带的腾讯年报校准
  - 不同领域 PDF 可能需要调整：
    ```bash
    uv run python scripts/calibrate_threshold.py <session_id_with_doc>
    ```
    输出 3 相关 + 3 无关 query 的分数表 + 建议值；按需写到 `.env`

## 演示流程

1. 把 `tests/fixtures/example/腾讯2025年度报告.pdf` 拖入上传区
2. 等待解析完成（约 30 秒，89 页）
3. 提问示例：
   - **事实**：腾讯 2025 年总营业收入是多少？
   - **摘要**：请总结主要业务板块
   - **对比**：2025 年净利润相比 2024 年增长了多少？
   - **边界**：今天天气如何？  → 明确说"未找到相关信息"

## 检索策略

1. PDF 用 `pdfplumber` 逐页提取文本（不含表格结构）
2. 按段落聚合到 ≤500 token + 80 overlap，按页边界硬切
3. BGE-large-zh-v1.5 中文向量化（1024 维），存入 PostgreSQL pgvector
4. 用户提问 → BGE 编码 → 取 top-16 → 过滤 similarity < `MIN_SIMILARITY`
5. 取前 8 chunks 给 Moonshot K2.6 综合作答
6. **严格约束**：必须先检索；仅基于检索结果作答；找不到必须说"未找到"

## 出处呈现

每条回答末尾渲染来源卡片：红色 PDF 徽章 + 文件名 + 蓝色页码徽章 + 2 行 snippet 截断；点击卡片展开完整 snippet。

## 局限性

- 表格只做文本提取，不保留结构
- 数值跨年比较依赖检索同时召回到两个年份的对应字段
- 单文档建议 ≤ 20 MB / ≤ 200 页
- 扫描版/纯图像 PDF 会在解析后被标记 failed（不报错，等用户删除）

## 项目结构

```
src/         FastAPI 后端
  api/         路由（chat、documents、sse）
  core/        引擎 + 内存服务 + prompt 模板 + tool 注册
  ingest/      PDF 解析 + chunker + ingestion 管线
  tools/       search_documents（V1 唯一 tool）
  llm/         Moonshot K2.6 客户端
  embedding/   BGE-large-zh-v1.5
  db/          SQLAlchemy 异步会话 + alembic
  models/      ORM 模型
frontend/    Next.js 15 前端
docs/        设计文档与实施计划
tests/       单元 + E2E
persona/     助手身份 + 行为准则
```

## 测试

```bash
pytest -q                    # 后端单元（默认跳过 LLM）
pytest -m llm -v             # E2E（需 MOONSHOT_API_KEY 和示例 PDF）
cd frontend && pnpm test     # 前端测试
```

## 截图

参见 [`docs/screenshots/`](docs/screenshots/)：

- `01-empty-state.png` — 空状态引导
- `02-uploading.png` — 解析中（进度条）
- `03-ready.png` — 文档就绪
- `04-answer-with-citation.png` — 回答 + 来源卡片
- `05-no-answer.png` — 文档外问题
- `06-after-restart.png` — 重启后历史保留

## 如果再给一周

- bge-reranker 二次排序提升精度
- 表格 layout-aware 解析（Camelot / unstructured）
- 全局知识库模式（跨会话引用）
- 流式上传 + 大文件支持
- ingestion cancel（处理中可删除）

## 设计文档

- 设计 spec：[docs/superpowers/specs/2026-04-25-doc-qa-design.md](docs/superpowers/specs/2026-04-25-doc-qa-design.md)
- 实施计划：[docs/superpowers/plans/2026-04-25-doc-qa-implementation.md](docs/superpowers/plans/2026-04-25-doc-qa-implementation.md)
```

- [ ] **Step 2: Capture 6 screenshots**

Manually using a browser (Chrome DevTools to capture exact dimensions, e.g. 1280×800):

1. **`01-empty-state.png`** — open http://localhost:3000, new session, screenshot the hero
2. **`02-uploading.png`** — drop a PDF in, capture during processing (progress bar visible)
3. **`03-ready.png`** — after status=ready (green row visible)
4. **`04-answer-with-citation.png`** — ask a factual question, capture answer + citation card
5. **`05-no-answer.png`** — ask "今天天气如何？", capture "未找到" response
6. **`06-after-restart.png`** — `docker compose restart backend`, refresh page, capture session list + previous messages still there

Save all 6 PNGs into `docs/screenshots/`.

- [ ] **Step 3: Commit**

```bash
mkdir -p docs/screenshots
git add README.md docs/screenshots/*.png
git commit -m "docs: README + 6 verification screenshots"
```

---

## Task 27: Push to GitHub + Final Smoke

**Goal:** Push to existing public repo `caiyin-bit/document-qa-assistant`. Verify clone-and-run works.

**Files:** none (operational)

> Note: The GitHub repo already exists at https://github.com/caiyin-bit/document-qa-assistant.
> The remote `origin` was wired up at session start. Auth setup (collaborator
> grant or `gh auth login` for the right account) was resolved separately —
> this task assumes `git push` succeeds.

- [ ] **Step 1: Push all commits**

```bash
git push -u origin main
```

- [ ] **Step 3: Clone-and-run smoke (in fresh tmp dir)**

```bash
cd /tmp
rm -rf doc-qa-smoke
gh repo clone caiyin-bit/document-qa-assistant doc-qa-smoke
cd doc-qa-smoke
cp .env.example .env
echo "MOONSHOT_API_KEY=$MOONSHOT_API_KEY" >> .env
docker compose up -d --build
sleep 60   # BGE model download
curl -fs http://localhost:8000/sessions -X POST
```

Expected: Returns `{"session_id": "..."}` JSON.

- [ ] **Step 4: Verify README renders on GitHub**

```bash
gh repo view --web
```

Check that the README shows correctly, screenshots load, structure looks professional.

- [ ] **Step 5: (Final commit if you adjusted anything)**

```bash
git add -A && git commit -m "chore: final polish" && git push
```

---

## Self-Review Checklist (run before declaring plan complete)

- [ ] Every spec section is covered by at least one task. Spot-check:
  - §1 standard responses → Tasks 10, 12 (templates + engine)
  - §3 data model → Task 1
  - §4 upload + ingestion + cleanup → Tasks 2, 3, 5, 6, 7
  - §4 startup recovery → Task 8
  - §4 delete + 409 → Task 7
  - §5 search tool + threshold → Task 9
  - §6 4-template prompts → Task 10
  - §7 SSE citations + DTO → Tasks 11, 12
  - §8 UI (empty hero / top bar / citation card) → Tasks 20, 21, 22
  - §10 tests → embedded in each backend task + E2E in 15
  - §11 scaffold copy → Task 0
  - §12 README → Task 26
  - §13 calibration → Task 14, MVP downgrade decisions covered in checkpoints below
  - §14 risks all have mitigations referenced in tasks (e.g. scanned-version → Task 5; threshold drift → Task 14)
  - §15 YAGNI scope respected — no tasks for multi-tenant / global KB / etc.

- [ ] No "TBD" / "TODO" / "fill in later" in any task body
- [ ] Function/method names consistent across tasks (e.g. `_mark_failed_and_clean`, `select_template`, `to_snippet`)
- [ ] Every code block is complete enough to copy-run
- [ ] All commits use conventional prefixes (feat/fix/chore/docs/test)
- [ ] No use of `--no-verify`

---

## MVP Downgrade Checkpoints (per spec §13)

If running behind, cut in this order **before** moving to later tasks:

| Checkpoint | If behind, cut |
|---|---|
| End of Day 1 (after Task 14) | Skip detailed progress (Task 21 → drop progress bar, keep spinner only); skip frontend component tests |
| Mid-Day 2 (after Task 21) | Skip click-to-expand on CitationCard; skip drag highlight |
| Day 2 evening (after Task 23) | Cut to P0: ensure upload + ingestion + search + citations + 4 no-answer states + docker work; skip beautifying |

Always ensure these P0s ship: upload + ingestion (with cleanup), search + threshold, citations binding + render, 4 no-answer states, docker compose, README + 4 screenshots (01/03/04/05).










