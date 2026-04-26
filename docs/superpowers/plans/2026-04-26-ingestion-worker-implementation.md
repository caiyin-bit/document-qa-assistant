# Ingestion Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PDF ingestion (text extraction + BGE embedding + pgvector insert) out of the FastAPI process into a dedicated Arq worker container, so chat is never blocked by encode and tasks survive backend reloads.

**Architecture:** Backend stays single-purpose (HTTP/SSE/chat + query-side embedding). New `worker` container runs `arq.WorkerSettings`, picks up `ingest_document` jobs from a new `redis` broker, owns the long-running ingestion. Both processes load BGE locally; all encode calls go through a per-process single-thread executor inside `BgeEmbedder` to keep the event loop free and avoid concurrent PyTorch races.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy 2 async, sentence-transformers (BAAI/bge-large-zh-v1.5), pgvector, **arq 0.28+**, **redis 7-alpine**, Docker Compose v2, pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-04-26-ingestion-worker-design.md](../specs/2026-04-26-ingestion-worker-design.md)

---

## File Structure

### Created

| Path | Responsibility |
|---|---|
| `src/worker/__init__.py` | Package marker |
| `src/worker/main.py` | `WorkerSettings`, `INGEST_MAX_TRIES`, `INGEST_TIMEOUT`, `_on_startup`, `_on_shutdown` |
| `src/worker/jobs.py` | `ingest_document(ctx, doc_id_str)` job function |
| `src/worker/redis_pool.py` | `make_redis_settings()` factory shared by backend + worker |
| `src/api/reaper.py` | `reenqueue_processing_documents(arq_pool, sm)` (replaces inline `cleanup_stale_documents` call) |
| `tests/unit/test_bge_embedder_async.py` | Async API + executor lifecycle tests |
| `tests/unit/test_worker_jobs.py` | Job-level unit tests (fake ctx, mocked deps) |
| `tests/unit/test_documents_enqueue.py` | Backend enqueue path: success / dedup / Redis-fail |
| `tests/unit/test_no_sync_embedder_in_async_paths.py` | Static grep-style guard |
| `tests/e2e/test_worker_e2e.py` | Real-redis end-to-end + fault injection |
| `docker-compose.test.yml` | Test stack with postgres + redis |

### Modified

| Path | Change |
|---|---|
| `src/embedding/bge_embedder.py` | Add `_executor`, `embed_batch_async`, `encode_one_async`, `close()` |
| `src/ingest/ingestion.py` | Use `embed_batch_async`; narrow `except` to business errors only; remove `_ingest_with_timeout` |
| `src/tools/search_documents.py` | Switch `encode_one` → `await encode_one_async` |
| `src/api/chat.py` | Update duck-type comment; ensure `embedder.encode_one` callsites all go via tool (already async) |
| `src/api/documents.py` | Replace `asyncio.create_task` with arq `enqueue_job(_job_id=...)` + structured logging; reorder upload steps so `os.replace` happens before enqueue; remove `_run_ingestion`, `_INGESTION_TASKS` |
| `src/main.py` | Add arq pool to lifespan + shutdown; call `embedder.close(wait=False)` on shutdown; replace `cleanup_stale_documents` startup hook with `reenqueue_processing_documents` |
| `src/ingest/ingestion.py` (existing `cleanup_stale_documents`) | Delete; reaper logic moves to `src/api/reaper.py` and uses arq |
| `pyproject.toml` | Add `arq>=0.26`, `redis>=5.0` |
| `docker-compose.yml` | Add `redis` service (with healthcheck), `worker` service (same image, different command); `backend.depends_on` add redis |
| `tests/conftest.py` | Add `arq_redis` fixture (real redis from compose) for integration tests; embedder cleanup fixture |

---

## Phase 1 — Embedder threading & lifecycle

### Task 1: BgeEmbedder gains async API + close()

**Files:**
- Modify: `src/embedding/bge_embedder.py`
- Test: `tests/unit/test_bge_embedder_async.py`

- [ ] **Step 1.1: Write failing test**

Create `tests/unit/test_bge_embedder_async.py`:

```python
"""Async API + executor lifecycle for BgeEmbedder."""
import asyncio
import time
import pytest

from src.embedding.bge_embedder import BgeEmbedder


class _FakeModel:
    """Stand-in for SentenceTransformer; records call thread + sleeps."""
    def __init__(self):
        self.call_threads: list[str] = []
        self.encode_delay = 0.0

    def encode(self, texts, **kw):
        import threading
        self.call_threads.append(threading.current_thread().name)
        if self.encode_delay:
            time.sleep(self.encode_delay)
        # Mimic shape: 2D numpy-like for batch, 1D for single
        if isinstance(texts, list):
            return [[0.1] * 1024 for _ in texts]
        return [0.1] * 1024


def _make_embedder(fake: _FakeModel) -> BgeEmbedder:
    e = BgeEmbedder(model_path="dummy", device="cpu")
    # Bypass cached_property to inject the fake
    e.__dict__["_model"] = fake
    return e


@pytest.mark.asyncio
async def test_embed_batch_async_returns_correct_shape():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    try:
        out = await emb.embed_batch_async(["a", "b", "c"])
        assert len(out) == 3
        assert all(len(v) == 1024 for v in out)
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_encode_one_async_returns_single_vector():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    try:
        out = await emb.encode_one_async("hello")
        assert len(out) == 1024
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_concurrent_encodes_are_serialized_in_one_thread():
    """max_workers=1 means concurrent encode_one_async calls run on the
    SAME thread one after another, never in parallel on the same model."""
    fake = _FakeModel()
    fake.encode_delay = 0.05
    emb = _make_embedder(fake)
    try:
        await asyncio.gather(
            emb.encode_one_async("a"),
            emb.encode_one_async("b"),
            emb.encode_one_async("c"),
        )
        assert len(set(fake.call_threads)) == 1, fake.call_threads
        assert all("bge" in t for t in fake.call_threads)
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_close_wait_true_drains_executor():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    await emb.encode_one_async("warm-up")  # spawns the worker thread
    threads_before = list(emb._executor._threads)
    emb.close(wait=True)
    # After wait=True shutdown, threads should have exited
    for t in threads_before:
        t.join(timeout=2.0)
        assert not t.is_alive(), f"thread {t.name} still alive after close(wait=True)"


@pytest.mark.asyncio
async def test_close_wait_false_returns_quickly():
    fake = _FakeModel()
    fake.encode_delay = 0.5  # in-flight batch will take 0.5s
    emb = _make_embedder(fake)
    task = asyncio.create_task(emb.embed_batch_async(["x"]))
    await asyncio.sleep(0.05)  # let the batch start
    t0 = time.monotonic()
    emb.close(wait=False)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"close(wait=False) blocked for {elapsed:.3f}s"
    # The in-flight task still completes
    await task
    # Final cleanup so pytest doesn't see lingering thread
    emb.close(wait=True)
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_bge_embedder_async.py -v
```

Expected: failures on `embed_batch_async`/`encode_one_async`/`close` (`AttributeError`).

- [ ] **Step 1.3: Implement async API + close**

Replace contents of `src/embedding/bge_embedder.py`:

```python
"""Local BGE embedder wrapping sentence-transformers.

bge-large-zh-v1.5 官方建议: 查询要加 instruction 前缀, 被检索的 passage 不加.
MVP 简化: 双侧都不加前缀(差异在一致性上抵消, 足够 MVP 用).

Threading: every encode call runs through `_executor` (max_workers=1) so
that (a) the asyncio event loop is never blocked by torch.encode, and
(b) concurrent callers in the same process serialize through one queue
instead of competing for the same SentenceTransformer instance.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property

from sentence_transformers import SentenceTransformer


class BgeEmbedder:
    def __init__(self, model_path: str = "BAAI/bge-large-zh-v1.5", device: str = "cpu") -> None:
        self._model_path = model_path
        self._device = device
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge")

    @cached_property
    def _model(self) -> SentenceTransformer:
        return SentenceTransformer(self._model_path, device=self._device)

    # --- sync entry points (internal helpers — do not call from async paths) ---

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(
            text, normalize_embeddings=True, convert_to_numpy=True
        )
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=16
        )
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs]

    def encode_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    # --- async entry points (use these from async code) ---

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.embed_batch, texts)

    async def encode_one_async(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.encode_one, text)

    def close(self, *, wait: bool = False) -> None:
        """Shutdown the executor.

        cancel_futures=True drops queued-but-not-started encodes. The
        currently-running batch (if any) finishes naturally — torch
        can't be interrupted mid-tensor-op.

        wait=False (default): return immediately. The worker thread
            keeps running until its in-flight batch completes; process
            exit is delayed by that thread but our caller is not.
        wait=True: block until the in-flight batch finishes. Use only
            where draining is verifiable (e.g. test fixtures).
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_bge_embedder_async.py -v
```

Expected: 5 PASS.

- [ ] **Step 1.5: Re-run existing embedder tests to confirm no regression**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_bge_embedder.py -v
```

Expected: 3 PASS (existing sync tests unaffected).

- [ ] **Step 1.6: Commit**

```bash
git add src/embedding/bge_embedder.py tests/unit/test_bge_embedder_async.py
git commit -m "feat(embedder): single-thread executor + async API + close()"
```

---

### Task 2: Wire BgeEmbedder.close() into FastAPI shutdown

**Files:**
- Modify: `src/main.py:87-102`
- Test: `tests/unit/test_startup_recovery.py` (extend existing) — verify shutdown event is registered

- [ ] **Step 2.1: Write failing test**

Append to `tests/unit/test_startup_recovery.py`:

```python
@pytest.mark.asyncio
async def test_shutdown_closes_embedder():
    """FastAPI shutdown event must call embedder.close(wait=False)."""
    import os
    os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    from src.main import make_app_default, _production_deps
    from unittest.mock import MagicMock

    _production_deps.cache_clear()
    app = make_app_default()
    deps = _production_deps()
    fake_close = MagicMock()
    deps.embedder.close = fake_close

    async with app.router.lifespan_context(app):
        pass  # shutdown fires when block exits

    fake_close.assert_called_once_with(wait=False)
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py::test_shutdown_closes_embedder -v
```

Expected: FAIL — no shutdown handler closes embedder.

- [ ] **Step 2.3: Add shutdown handler in `src/main.py`**

In `make_app_default()` after the existing `@app.on_event("startup")`, add:

```python
    @app.on_event("shutdown")
    async def _close_embedder_on_shutdown():
        deps.embedder.close(wait=False)
```

- [ ] **Step 2.4: Run test to verify it passes**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py -v
```

Expected: existing tests still pass + new test PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/main.py tests/unit/test_startup_recovery.py
git commit -m "feat(backend): close BGE executor on FastAPI shutdown"
```

---

### Task 3: Switch ingestion + chat tools to async embedder

**Files:**
- Modify: `src/ingest/ingestion.py:77`
- Modify: `src/tools/search_documents.py:39`
- Test: existing tests must keep passing with mocked embedder; add a guard test in Task 16

- [ ] **Step 3.1: Update existing ingestion unit tests for async embedder**

In `tests/unit/test_ingestion_failure_cleanup.py` and `tests/unit/test_ingestion_phases.py`, change the mocked embedder from sync to async — find every `embedder.embed_batch = MagicMock(...)` and change to `embedder.embed_batch_async = AsyncMock(...)` with the same return values.

Example edit in `test_ingestion_failure_cleanup.py`:

```python
# before
embedder.embed_batch = MagicMock(side_effect=[[1.0]*1024, RuntimeError("boom")])

# after
from unittest.mock import AsyncMock
embedder.embed_batch_async = AsyncMock(side_effect=[[1.0]*1024, RuntimeError("boom")])
```

Apply the same change in any other unit test that mocks `embed_batch` — `grep -rn "embed_batch" tests/unit/`.

- [ ] **Step 3.2: Run those tests; expect failure (production code still calls sync)**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_ingestion_failure_cleanup.py tests/unit/test_ingestion_phases.py -v
```

Expected: FAIL — `_ingest_document` still calls `embedder.embed_batch` not `embed_batch_async`.

- [ ] **Step 3.3: Switch `_ingest_document` to async embedder**

In `src/ingest/ingestion.py` find the line:

```python
embeddings = embedder.embed_batch(contents)
```

Replace with:

```python
embeddings = await embedder.embed_batch_async(contents)
```

- [ ] **Step 3.4: Switch `search_documents` to async embedder**

In `src/tools/search_documents.py:39` find:

```python
emb = self.embedder.encode_one(query)
```

The function calling this is `async def`, so:

```python
emb = await self.embedder.encode_one_async(query)
```

If that line is inside a sync method, escalate the method to async and update its caller. Run `grep -rn "search_documents" src/` to confirm caller chain (likely already async via the chat tool dispatcher).

- [ ] **Step 3.5: Run impacted tests**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_ingestion_failure_cleanup.py tests/unit/test_ingestion_phases.py tests/unit/test_search_documents.py -v
```

Expected: all PASS.

- [ ] **Step 3.6: Run the full unit suite to catch any other call sites**

```bash
docker compose exec -T backend uv run pytest tests/unit/ -v
```

Expected: all PASS (or fix any other tests that mocked sync embed; same edit pattern).

- [ ] **Step 3.7: Commit**

```bash
git add src/ingest/ingestion.py src/tools/search_documents.py tests/unit/
git commit -m "refactor(ingest+search): use async embedder API to free event loop"
```

---

## Phase 2 — Exception classification in _ingest_document

### Task 4: Narrow `except Exception` to business-only

**Files:**
- Modify: `src/ingest/ingestion.py` — replace the broad except
- Test: `tests/unit/test_ingestion_failure_cleanup.py` — add infra-error test

- [ ] **Step 4.1: Write failing test for infra-error propagation**

Append to `tests/unit/test_ingestion_failure_cleanup.py`:

```python
@pytest.mark.asyncio
async def test_infra_error_propagates_for_arq_retry():
    """DB connection errors must NOT be swallowed; Arq retry depends on
    the job function raising for non-business failures."""
    from sqlalchemy.exc import OperationalError

    mem = MagicMock()
    mem.bulk_insert_chunks = AsyncMock(side_effect=OperationalError("conn", {}, Exception("blip")))
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock(return_value=[[0.0]*1024])
    parser = lambda path: iter([(1, "page text")])
    chunker = lambda text, page_no: [{"content": text, "page_no": page_no}]

    with pytest.raises(OperationalError):
        await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                                mem=mem, embedder=embedder,
                                iter_pages=parser, chunker=chunker)

    # No mark-failed call — Arq should retry
    for c in mem.update_document.await_args_list:
        assert c.kwargs.get("status") != DocumentStatus.failed
    mem.delete_chunks_for_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_pdf_validation_error_marks_failed():
    """PdfValidationError is a business error → mark failed and return."""
    from src.ingest.pdf_parser import PdfValidationError

    def bad_parser(path):
        raise PdfValidationError("PDF 损坏")
        yield  # make it a generator
    mem = MagicMock()
    mem.update_document = AsyncMock()
    mem.delete_chunks_for_document = AsyncMock()
    embedder = MagicMock()
    embedder.embed_batch_async = AsyncMock()

    await _ingest_document("doc-id", path=Path("/tmp/x.pdf"),
                            mem=mem, embedder=embedder,
                            iter_pages=bad_parser,
                            chunker=lambda *a, **kw: [])

    last = mem.update_document.await_args_list[-1]
    assert last.kwargs.get("status") == DocumentStatus.failed
    assert "损坏" in last.kwargs.get("error_message", "")
```

- [ ] **Step 4.2: Run tests to verify infra test fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_ingestion_failure_cleanup.py -v
```

Expected: `test_infra_error_propagates_for_arq_retry` FAILS (current code swallows everything).

- [ ] **Step 4.3: Narrow the except in `_ingest_document`**

In `src/ingest/ingestion.py`, find the trailing `except Exception as e:` block and replace it. Full updated function tail:

```python
        if total_chunks == 0:
            await _mark_failed_and_clean(
                doc_id, "未能从 PDF 中提取任何文本（疑似扫描版或纯图像 PDF）",
                mem=mem,
            )
            return

        await mem.update_document(
            doc_id, status=DocumentStatus.ready, progress_phase=None,
        )
    except PdfValidationError as e:
        # Business: PDF content invalid — mark failed and stop. Arq sees
        # the job as completed normally, no retry.
        await _mark_failed_and_clean(doc_id, str(e), mem=mem)
        log.warning("ingestion business-failed for %s: %s", doc_id, e)
    # All other exceptions propagate so Arq can count the try and retry
    # within max_tries.
```

Add the import at the top of `src/ingest/ingestion.py`:

```python
from src.ingest.pdf_parser import PdfValidationError
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_ingestion_failure_cleanup.py tests/unit/test_ingestion_phases.py -v
```

Expected: all PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/ingest/ingestion.py tests/unit/test_ingestion_failure_cleanup.py
git commit -m "refactor(ingest): only catch business errors; let infra propagate for retry"
```

---

## Phase 3 — Worker module

### Task 5: Worker constants + redis settings factory

**Files:**
- Create: `src/worker/__init__.py`
- Create: `src/worker/redis_pool.py`

- [ ] **Step 5.1: Create empty package marker**

Create `src/worker/__init__.py` with content:

```python
"""Arq-based ingestion worker. See docs/superpowers/specs/2026-04-26-ingestion-worker-design.md"""
```

- [ ] **Step 5.2: Create redis settings factory**

Create `src/worker/redis_pool.py`:

```python
"""Shared Redis connection settings used by both backend (enqueue side)
and worker (consume side)."""
from __future__ import annotations

import os

from arq.connections import RedisSettings


def make_redis_settings() -> RedisSettings:
    """Build RedisSettings from REDIS_URL env. Raise if unset — fail-fast
    behavior matches Config in src/main.py."""
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL env var is required for ingestion worker")
    return RedisSettings.from_dsn(url)
```

- [ ] **Step 5.3: Commit**

```bash
git add src/worker/__init__.py src/worker/redis_pool.py
git commit -m "feat(worker): redis settings factory"
```

---

### Task 6: Job function — happy path + missing-file preflight + step-1 reset

**Files:**
- Create: `src/worker/jobs.py`
- Create: `tests/unit/test_worker_jobs.py`

- [ ] **Step 6.1: Write failing happy-path + preflight tests**

Create `tests/unit/test_worker_jobs.py`:

```python
"""Unit tests for `ingest_document` Arq job. Uses fake ctx + mocked deps;
no real Redis or Postgres needed (those live in tests/e2e/)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call
from uuid import UUID, uuid4

import pytest


DOC_ID = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def fake_sm(tmp_path):
    """Sessionmaker that yields a MagicMock-shaped 'mem' on each enter."""
    sessions: list = []

    class _Sm:
        def __call__(self):
            mem = MagicMock()
            mem.delete_chunks_for_document = AsyncMock()
            mem.update_document = AsyncMock()
            mem.bulk_insert_chunks = AsyncMock()
            sess = AsyncMock()
            sess.__aenter__ = AsyncMock(return_value=sess)
            sess.__aexit__ = AsyncMock(return_value=None)
            sess._mem = mem  # for assertions
            sessions.append(sess)
            return sess

    sm = _Sm()
    sm.sessions = sessions  # type: ignore[attr-defined]
    return sm


@pytest.fixture
def fake_embedder():
    e = MagicMock()
    e.embed_batch_async = AsyncMock(return_value=[[0.0] * 1024])
    return e


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr("src.worker.jobs.UPLOADS_DIR", d)
    return d


def _make_pdf(uploads_dir: Path, doc_id: UUID) -> Path:
    """Drop a tiny valid-ish PDF stub at uploads/{doc_id}.pdf.
    For unit tests we mock iter_pages so the file just needs to exist."""
    p = uploads_dir / f"{doc_id}.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake\n")
    return p


@pytest.mark.asyncio
async def test_ingest_document_missing_file_marks_failed(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """If uploads/{doc_id}.pdf is missing (e.g. crash between INSERT and
    rename), worker step 2 marks the doc failed with a clear message and
    returns (no Arq retry)."""
    from src.worker.jobs import ingest_document

    ctx = {
        "sessionmaker": fake_sm,
        "embedder": fake_embedder,
        "job_try": 1,
    }
    # Note: file deliberately NOT created
    await ingest_document(ctx, str(DOC_ID))

    # Exactly one session opened (preflight branch)
    assert len(fake_sm.sessions) == 1
    mem = fake_sm.sessions[0]._mem
    last = mem.update_document.await_args_list[-1]
    from src.models.schemas import DocumentStatus
    assert last.kwargs["status"] == DocumentStatus.failed
    assert "未落盘" in last.kwargs["error_message"]


@pytest.mark.asyncio
async def test_ingest_document_step1_resets_state(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """When file exists, step 1 deletes chunks + resets progress fields
    BEFORE ingestion runs."""
    from src.worker.jobs import ingest_document

    _make_pdf(uploads_dir, DOC_ID)

    # Patch _ingest_document to record what state mem was in when called
    captured = {}

    async def fake_ingest(doc_id, *, path, mem, embedder, iter_pages, chunker):
        # Snapshot await counts at the moment ingestion starts
        captured["delete_count"] = mem.delete_chunks_for_document.await_count
        captured["update_calls"] = list(mem.update_document.await_args_list)

    monkeypatch.setattr("src.worker.jobs._ingest_document", fake_ingest)

    ctx = {"sessionmaker": fake_sm, "embedder": fake_embedder, "job_try": 1}
    await ingest_document(ctx, str(DOC_ID))

    assert captured["delete_count"] == 1
    # Last reset call before ingestion: progress_page=0, error_message=None
    reset = next(c for c in reversed(captured["update_calls"])
                  if c.kwargs.get("progress_page") == 0)
    assert reset.kwargs.get("progress_phase") is None
    assert reset.kwargs.get("error_message") is None


@pytest.mark.asyncio
async def test_ingest_document_happy_path_invokes_ingestion(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """File exists + ingestion succeeds → _ingest_document called with
    correct args."""
    from src.worker.jobs import ingest_document

    pdf = _make_pdf(uploads_dir, DOC_ID)
    captured_args = {}

    async def fake_ingest(doc_id, *, path, mem, embedder, iter_pages, chunker):
        captured_args.update(
            doc_id=doc_id, path=path, embedder=embedder,
            iter_pages=iter_pages, chunker=chunker,
        )

    monkeypatch.setattr("src.worker.jobs._ingest_document", fake_ingest)

    ctx = {"sessionmaker": fake_sm, "embedder": fake_embedder, "job_try": 1}
    await ingest_document(ctx, str(DOC_ID))

    assert captured_args["doc_id"] == DOC_ID
    assert captured_args["path"] == pdf
    assert captured_args["embedder"] is fake_embedder
```

- [ ] **Step 6.2: Run to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_worker_jobs.py -v
```

Expected: ImportError — `src.worker.jobs` does not exist.

- [ ] **Step 6.3: Implement happy-path version of `ingest_document`**

Create `src/worker/jobs.py`:

```python
"""Arq job: ingest a single uploaded PDF.

Spec: docs/superpowers/specs/2026-04-26-ingestion-worker-design.md §3.2.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from src.core.memory_service import MemoryService
from src.ingest.chunker import chunk
from src.ingest.ingestion import _ingest_document, _mark_failed_and_clean
from src.ingest.pdf_parser import iter_pages
from src.models.schemas import DocumentStatus

log = logging.getLogger(__name__)

# Constants imported from main so func() in WorkerSettings stays the
# single source of truth (see test_worker_jobs::test_max_tries_constant_consistent).
INGEST_MAX_TRIES = 2
INGEST_TIMEOUT = 1800

UPLOADS_DIR = Path("data/uploads")


async def ingest_document(ctx, doc_id_str: str) -> None:
    """Idempotent ingestion job.

    Step 1: preflight — verify the PDF exists on disk; if not, mark failed
    and return (this is a business error, not retryable).
    Step 2: reset — delete any partial chunks from a previous crashed
    try, reset progress fields.
    Step 3: run — call the existing `_ingest_document` pipeline.
    Cancellation handled at outer try/except so the inner session can
    finish __aexit__ before any fresh-session work runs.
    """
    doc_id = UUID(doc_id_str)
    sm = ctx["sessionmaker"]
    embedder = ctx["embedder"]
    job_try = ctx.get("job_try", 1)
    log.info("event=ingest.start doc_id=%s job_try=%d max_tries=%d",
              doc_id, job_try, INGEST_MAX_TRIES)

    path = UPLOADS_DIR / f"{doc_id}.pdf"
    if not path.is_file():
        async with sm() as db:
            mem = MemoryService(db)
            await mem.update_document(
                doc_id, status=DocumentStatus.failed,
                error_message="上传文件未落盘，请删除后重新上传",
                progress_phase=None,
            )
        log.warning("event=ingest.failed.business doc_id=%s reason=missing_file", doc_id)
        return

    # Step 2: idempotent reset
    async with sm() as db:
        mem = MemoryService(db)
        deleted = await mem.delete_chunks_for_document(doc_id)
        await mem.update_document(
            doc_id, status=DocumentStatus.processing,
            progress_page=0, progress_phase=None, error_message=None,
        )
    log.info("event=ingest.reset doc_id=%s deleted_chunks=%s", doc_id, deleted)

    # Step 3: run. CancelledError handler is added in Task 7.
    async with sm() as db:
        mem = MemoryService(db)
        await _ingest_document(
            doc_id, path=path, mem=mem, embedder=embedder,
            iter_pages=iter_pages, chunker=chunk,
        )
    log.info("event=ingest.ready doc_id=%s", doc_id)
```

- [ ] **Step 6.4: Run to verify happy-path tests pass**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_worker_jobs.py -v
```

Expected: 3 PASS.

- [ ] **Step 6.5: Commit**

```bash
git add src/worker/jobs.py tests/unit/test_worker_jobs.py
git commit -m "feat(worker): ingest_document job with preflight + idempotent reset"
```

---

### Task 7: CancelledError handling — non-last try and last try

**Files:**
- Modify: `src/worker/jobs.py`
- Test: `tests/unit/test_worker_jobs.py`

- [ ] **Step 7.1: Write failing tests for cancellation paths**

Append to `tests/unit/test_worker_jobs.py`:

```python
@pytest.mark.asyncio
async def test_cancel_non_last_try_does_not_touch_db(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """job_try=1 + cancel during ingestion → re-raise, no fresh-session
    mark-failed (let next retry's step-1 clean up)."""
    from src.worker.jobs import ingest_document, INGEST_MAX_TRIES
    assert INGEST_MAX_TRIES >= 2

    _make_pdf(uploads_dir, DOC_ID)

    async def cancel_mid(doc_id, *, path, mem, **kw):
        raise asyncio.CancelledError()

    monkeypatch.setattr("src.worker.jobs._ingest_document", cancel_mid)

    ctx = {"sessionmaker": fake_sm, "embedder": fake_embedder, "job_try": 1}
    with pytest.raises(asyncio.CancelledError):
        await ingest_document(ctx, str(DOC_ID))

    # Sessions opened: step-2 reset (1) + step-3 run (1) = 2.
    # The reset session's update is BEFORE cancel; no failed mark anywhere.
    from src.models.schemas import DocumentStatus
    all_updates = []
    for sess in fake_sm.sessions:
        all_updates.extend(sess._mem.update_document.await_args_list)
    assert not any(c.kwargs.get("status") == DocumentStatus.failed for c in all_updates)


@pytest.mark.asyncio
async def test_cancel_last_try_marks_failed_in_fresh_session(
    fake_sm, fake_embedder, uploads_dir, monkeypatch
):
    """job_try=INGEST_MAX_TRIES + cancel → fresh session marks failed,
    deletes partial chunks, error_message written; CancelledError still
    re-raised so Arq stops retrying."""
    from src.worker.jobs import ingest_document, INGEST_MAX_TRIES

    _make_pdf(uploads_dir, DOC_ID)

    async def cancel_mid(doc_id, *, path, mem, **kw):
        raise asyncio.CancelledError()

    monkeypatch.setattr("src.worker.jobs._ingest_document", cancel_mid)

    ctx = {
        "sessionmaker": fake_sm, "embedder": fake_embedder,
        "job_try": INGEST_MAX_TRIES,
    }
    with pytest.raises(asyncio.CancelledError):
        await ingest_document(ctx, str(DOC_ID))

    # 3 sessions: reset, run, fresh-mark-failed
    assert len(fake_sm.sessions) == 3, [s for s in fake_sm.sessions]
    fresh_mem = fake_sm.sessions[2]._mem
    fresh_mem.delete_chunks_for_document.assert_awaited_once_with(DOC_ID)
    failed_call = next(c for c in fresh_mem.update_document.await_args_list
                        if c.kwargs.get("status") == DocumentStatus.failed)
    assert "解析多次" in failed_call.kwargs["error_message"]


@pytest.mark.asyncio
async def test_max_tries_constant_consistent():
    """The MAX_TRIES used by the wrapper must equal what's registered
    with arq.worker.func — guards against silent drift if someone bumps
    one but not the other."""
    from src.worker.jobs import INGEST_MAX_TRIES
    from src.worker.main import WorkerSettings
    fn = WorkerSettings.functions[0]
    assert fn.max_tries == INGEST_MAX_TRIES, (fn.max_tries, INGEST_MAX_TRIES)
```

(`DocumentStatus` import already at top of test file via Task 6.)

- [ ] **Step 7.2: Run to verify they fail**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_worker_jobs.py -v
```

Expected: cancel tests fail (job currently doesn't catch); max_tries test fails on missing `WorkerSettings`.

- [ ] **Step 7.3: Update `src/worker/jobs.py` — wrap step-3 with try/except**

Replace the step-3 block in `ingest_document` with:

```python
    # Step 3: run. CRITICAL ordering: try/except wraps the entire
    # `async with sm()` block, NOT a try inside it. Reason: if cancel
    # fires mid-bulk_insert_chunks, the session has a pending statement;
    # opening a fresh session inside the still-active `async with` would
    # race with the original session's __aexit__ (rollback/close). By
    # wrapping at this level the original session has fully unwound by
    # the time we reach the handler.
    try:
        async with sm() as db:
            mem = MemoryService(db)
            await _ingest_document(
                doc_id, path=path, mem=mem, embedder=embedder,
                iter_pages=iter_pages, chunker=chunk,
            )
    except asyncio.CancelledError:
        log.warning("event=ingest.cancelled doc_id=%s job_try=%d last_try=%s",
                     doc_id, job_try, job_try >= INGEST_MAX_TRIES)
        if job_try >= INGEST_MAX_TRIES:
            async def _final_mark_failed():
                async with sm() as fresh:
                    fmem = MemoryService(fresh)
                    await _mark_failed_and_clean(
                        doc_id, "解析多次超时/中断，请删除后重试",
                        mem=fmem,
                    )
            try:
                await asyncio.shield(asyncio.wait_for(
                    _final_mark_failed(), timeout=5.0))
            except Exception:
                log.warning("final mark-failed for %s also failed", doc_id)
        raise
    log.info("event=ingest.ready doc_id=%s", doc_id)
```

- [ ] **Step 7.4: Run to verify cancel tests pass (max_tries test still fails)**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_worker_jobs.py -v -k "cancel"
```

Expected: cancel tests PASS. max_tries test still fails (WorkerSettings doesn't exist).

- [ ] **Step 7.5: Commit**

```bash
git add src/worker/jobs.py tests/unit/test_worker_jobs.py
git commit -m "feat(worker): cancel-aware last-try mark-failed via fresh session"
```

---

### Task 8: WorkerSettings + on_startup/on_shutdown

**Files:**
- Create: `src/worker/main.py`
- Test: `tests/unit/test_worker_jobs.py::test_max_tries_constant_consistent` (already written in Task 7)

- [ ] **Step 8.1: Implement `src/worker/main.py`**

Create the file:

```python
"""Arq WorkerSettings entry point.

Run from container as:
    uv run arq src.worker.main.WorkerSettings

Spec: docs/superpowers/specs/2026-04-26-ingestion-worker-design.md §3.2.
"""
from __future__ import annotations

import logging

from arq.worker import func
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import load_config
from src.db.session import make_engine, make_sessionmaker
from src.embedding.bge_embedder import BgeEmbedder
from src.worker.jobs import INGEST_MAX_TRIES, INGEST_TIMEOUT, ingest_document
from src.worker.redis_pool import make_redis_settings

log = logging.getLogger(__name__)


async def _on_startup(ctx: dict) -> None:
    """Build per-process singletons and attach them to ctx so jobs reuse them."""
    cfg = load_config()
    engine = make_engine(cfg.db.url)
    sm: async_sessionmaker = make_sessionmaker(engine)
    embedder = BgeEmbedder(model_path=cfg.embedding.model_path, device=cfg.embedding.device)

    ctx["engine"] = engine
    ctx["sessionmaker"] = sm
    ctx["embedder"] = embedder
    log.info("worker startup: deps wired (db + embedder)")


async def _on_shutdown(ctx: dict) -> None:
    embedder: BgeEmbedder = ctx.get("embedder")  # type: ignore[assignment]
    if embedder is not None:
        embedder.close(wait=False)
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker shutdown: embedder + engine closed")


class WorkerSettings:
    functions = [
        func(ingest_document, name="ingest_document",
             timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES),
    ]
    redis_settings = make_redis_settings()
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 1
    keep_result = 60
```

- [ ] **Step 8.2: Run the constant-consistency test**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_worker_jobs.py::test_max_tries_constant_consistent -v
```

Expected: PASS.

> ⚠️ This test imports `make_redis_settings` which raises if `REDIS_URL` is unset. The Docker backend container will get the env var in Task 9. For now, the test runs inside `docker compose exec backend` which doesn't have it. Set it inline:
> ```bash
> docker compose exec -T -e REDIS_URL=redis://redis:6379/0 backend uv run pytest tests/unit/test_worker_jobs.py -v
> ```

- [ ] **Step 8.3: Run the full worker test suite**

```bash
docker compose exec -T -e REDIS_URL=redis://redis:6379/0 backend uv run pytest tests/unit/test_worker_jobs.py -v
```

Expected: all PASS.

- [ ] **Step 8.4: Commit**

```bash
git add src/worker/main.py
git commit -m "feat(worker): WorkerSettings with startup/shutdown wiring"
```

---

## Phase 4 — Backend integration

### Task 9: Add arq + redis to deps and docker-compose

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`

- [ ] **Step 9.1: Add arq + redis to pyproject**

In `pyproject.toml`, find the `dependencies = [...]` block and add (alphabetical order respected):

```toml
    "arq>=0.26",
    "redis>=5.0",
```

- [ ] **Step 9.2: Update lock file**

```bash
uv lock
```

- [ ] **Step 9.3: Add redis service to docker-compose.yml**

Add under `services:`, between `postgres:` and `backend:`:

```yaml
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 10
```

- [ ] **Step 9.4: Add worker service**

Add after the `backend:` block, before `volumes:`:

```yaml
  worker:
    build: .
    command: sh -c "uv run arq src.worker.main.WorkerSettings"
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/docqa
      REDIS_URL: redis://redis:6379/0
      MOONSHOT_API_KEY: ${MOONSHOT_API_KEY}
      MOONSHOT_BASE_URL: ${MOONSHOT_BASE_URL:-https://api.siliconflow.cn/v1}
      MOONSHOT_MODEL_ID: ${MOONSHOT_MODEL_ID:-Pro/moonshotai/Kimi-K2.6}
      APP_USER_ID: ${APP_USER_ID:-00000000-0000-0000-0000-000000000001}
      HF_HOME: /root/.cache/huggingface
    volumes:
      - ./src:/app/src
      - ./persona:/app/persona
      - ./scripts:/app/scripts
      - ./config.yaml:/app/config.yaml
      - ./data/uploads:/app/data/uploads
      - ${HOME}/.cache/huggingface:/root/.cache/huggingface
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
```

- [ ] **Step 9.5: Add `REDIS_URL` to backend env + redis dependency**

In `backend.environment`, add after `APP_USER_ID`:

```yaml
      REDIS_URL: redis://redis:6379/0
```

In `backend.depends_on`, add:

```yaml
      redis:
        condition: service_healthy
```

- [ ] **Step 9.6: Bring up the new stack**

```bash
./dev.sh down
./dev.sh -d
docker compose ps
```

Expected: 4 containers running (postgres, redis, backend, worker), all healthy.

- [ ] **Step 9.7: Confirm worker logs show startup**

```bash
docker compose logs worker --tail=30
```

Expected: lines containing `worker startup: deps wired`, `Starting worker for ...`, no errors. (Job consumption will fail until backend sends jobs in Task 11.)

- [ ] **Step 9.8: Commit**

```bash
git add pyproject.toml uv.lock docker-compose.yml
git commit -m "chore: redis + worker container, arq dependency"
```

---

### Task 10: Backend lifespan creates arq pool

**Files:**
- Modify: `src/main.py`
- Modify: `src/api/chat.py` and `src/api/documents.py` to receive arq pool via deps
- Test: extend `tests/unit/test_startup_recovery.py`

- [ ] **Step 10.1: Write failing test for arq pool wiring**

Append to `tests/unit/test_startup_recovery.py`:

```python
@pytest.mark.asyncio
async def test_lifespan_creates_and_closes_arq_pool(monkeypatch):
    """Backend startup must create an arq Redis pool; shutdown must close it."""
    import os
    os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    os.environ["REDIS_URL"] = "redis://redis:6379/0"

    from src.main import _production_deps, make_app_default
    _production_deps.cache_clear()

    pool_close_count = 0
    real_create = None

    from arq import create_pool as _create_pool
    from src.main import make_app_default
    real_create = _create_pool

    created_pools = []

    async def fake_create(settings, **kw):
        pool = await real_create(settings, **kw)
        created_pools.append(pool)
        return pool

    monkeypatch.setattr("src.main.create_pool", fake_create)
    app = make_app_default()
    async with app.router.lifespan_context(app):
        assert len(created_pools) == 1
    # After shutdown, pool's connection should be closed
    assert created_pools[0].connection_pool._created_connections == 0 or \
            not created_pools[0].connection_pool.connection_kwargs
```

> The exact pool-closed assertion is brittle across redis-py versions. If the version probe fails, fall back to `assert created_pools[0].connection_pool._available_connections is None or len(created_pools[0].connection_pool._available_connections) == 0` — adjust at implementation time.

- [ ] **Step 10.2: Run to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py::test_lifespan_creates_and_closes_arq_pool -v
```

Expected: FAIL — `src.main.create_pool` doesn't exist (not imported yet).

- [ ] **Step 10.3: Add arq pool to backend deps**

In `src/main.py`:

1. Add import at top:
   ```python
   from arq import create_pool
   from src.worker.redis_pool import make_redis_settings
   ```

2. Inside `make_app_default()` after the `cleanup_stale_documents` startup hook, add:

   ```python
       _arq_pool_holder: dict = {}

       @app.on_event("startup")
       async def _create_arq_pool():
           pool = await create_pool(make_redis_settings())
           _arq_pool_holder["pool"] = pool
           # Make available to routers via app.state
           app.state.arq_pool = pool

       @app.on_event("shutdown")
       async def _close_arq_pool():
           pool = _arq_pool_holder.get("pool")
           if pool is not None:
               await pool.aclose()
   ```

   Place this BEFORE the existing `_close_embedder_on_shutdown` so embedder closes after pool (correct teardown order; worker side mirrors).

- [ ] **Step 10.4: Run test to verify it passes**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py -v
```

Expected: all PASS.

- [ ] **Step 10.5: Commit**

```bash
git add src/main.py tests/unit/test_startup_recovery.py
git commit -m "feat(backend): create arq pool in lifespan"
```

---

### Task 11: Replace asyncio.create_task with arq enqueue + structured logging

**Files:**
- Modify: `src/api/documents.py`
- Test: `tests/unit/test_documents_enqueue.py` (new)

- [ ] **Step 11.1: Write failing tests for enqueue path**

Create `tests/unit/test_documents_enqueue.py`:

```python
"""Backend upload endpoint: arq enqueue happy path + Redis failure +
de-dup result classification."""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")

from src.main import _production_deps

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


@pytest.fixture(autouse=True)
def reset_lru_caches():
    import src.db.session as _ses
    _production_deps.cache_clear()
    _ses._default_sm = None
    yield
    _production_deps.cache_clear()
    _ses._default_sm = None


@pytest_asyncio.fixture
async def fake_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="ingest:xxx"))
    return pool


@pytest_asyncio.fixture
async def client(db_session, fake_pool):
    from src.main import make_app_default
    app = make_app_default()
    transport = ASGITransport(app=app)
    # Stub the pool so tests don't need real Redis
    async with app.router.lifespan_context(app):
        app.state.arq_pool = fake_pool
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def session_id(client):
    r = await client.post("/sessions")
    assert r.status_code == 200
    return r.json()["session_id"]


@pytest.mark.asyncio
async def test_upload_calls_enqueue_with_deterministic_job_id(
    client, session_id, fake_pool
):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]
    fake_pool.enqueue_job.assert_awaited_once()
    args, kwargs = fake_pool.enqueue_job.call_args
    assert args[0] == "ingest_document"
    assert args[1] == doc_id
    assert kwargs.get("_job_id") == f"ingest:{doc_id}"


@pytest.mark.asyncio
async def test_upload_handles_redis_failure_returns_503(
    client, session_id, fake_pool
):
    from redis.exceptions import RedisError
    fake_pool.enqueue_job = AsyncMock(side_effect=RedisError("down"))
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 503, r.text
    assert "队列" in r.json().get("detail", "")
    # Disk file cleaned up
    leftovers = list(Path("data/uploads").glob("*.pdf"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_upload_atomic_rename_happens_before_enqueue(
    client, session_id, fake_pool
):
    """When enqueue is called, the final PDF must already exist on disk."""
    seen_existence: list[bool] = []

    async def check_then_record(*args, **kwargs):
        doc_id = args[1]
        path = Path(f"data/uploads/{doc_id}.pdf")
        seen_existence.append(path.is_file())
        return MagicMock(job_id=f"ingest:{doc_id}")

    fake_pool.enqueue_job = AsyncMock(side_effect=check_then_record)
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200
    assert seen_existence == [True]
```

- [ ] **Step 11.2: Run to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_documents_enqueue.py -v
```

Expected: FAIL — backend still calls `_run_ingestion`, not arq.

- [ ] **Step 11.3: Modify `src/api/documents.py`**

Replace the body of `upload_document` from "atomic rename" through "launch background ingestion" with:

```python
        # 4) atomic rename (must happen BEFORE enqueue so worker sees the file)
        final_path = UPLOADS_DIR / f"{document_id}.pdf"
        try:
            os.replace(temp_path, final_path)
        except Exception:
            await mem.delete_document(document_id)
            temp_path.unlink(missing_ok=True)
            raise HTTPException(500, "文件落盘失败")

        # 5) enqueue ingestion job (deterministic _job_id for dedup with reaper)
        from redis.exceptions import RedisError
        from fastapi import Request
        # Access pool via app state — Request is injected by FastAPI
        # (see signature change below).
        try:
            job = await request.app.state.arq_pool.enqueue_job(
                "ingest_document", str(document_id),
                _job_id=f"ingest:{document_id}",
            )
            result = "queued" if job is not None else "deduped"
        except RedisError as e:
            result = "redis_error"
            log.error("event=ingest.enqueue doc_id=%s job_id=ingest:%s result=%s err=%s",
                       document_id, document_id, result, e)
            # Best-effort cleanup
            try:
                await mem.delete_document(document_id)
            except Exception:
                pass
            final_path.unlink(missing_ok=True)
            raise HTTPException(503, "任务队列不可达，请稍后重试")
        log.info("event=ingest.enqueue doc_id=%s job_id=ingest:%s result=%s",
                  document_id, document_id, result)

        # 6) return
        return {
            "document_id": str(document_id),
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "page_count": doc.page_count,
        }
```

Add `request: Request` to the endpoint signature:

```python
    @router.post("/sessions/{session_id}/documents")
    async def upload_document(
        session_id: UUID,
        request: Request,                                  # NEW
        file: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
    ):
```

Add the import:

```python
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
```

Delete the now-unused `_run_ingestion` function and `_INGESTION_TASKS` set, and remove the `import asyncio` if no longer needed.

- [ ] **Step 11.4: Run tests**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_documents_enqueue.py tests/unit/test_api_documents.py -v
```

Expected: enqueue tests PASS; legacy tests in `test_api_documents.py` may need their fixture updated — find:

```python
with patch("src.api.documents._run_ingestion", new=AsyncMock(return_value=None)):
```

Replace with `app.state.arq_pool` stubbed to a `MagicMock()` whose `enqueue_job` is `AsyncMock(return_value=...)` (mirror the new fixture in `test_documents_enqueue.py`).

- [ ] **Step 11.5: Commit**

```bash
git add src/api/documents.py tests/unit/test_documents_enqueue.py tests/unit/test_api_documents.py
git commit -m "feat(api): enqueue ingestion via arq + structured result logging"
```

---

### Task 12: Reaper rewrite — only enqueue, dedup via _job_id

**Files:**
- Create: `src/api/reaper.py`
- Modify: `src/main.py` to use the new reaper
- Modify: `src/ingest/ingestion.py` — remove `cleanup_stale_documents` (logic moves)
- Test: `tests/unit/test_startup_recovery.py` — rewrite

- [ ] **Step 12.1: Update existing startup-recovery tests**

In `tests/unit/test_startup_recovery.py`, find the test that asserts `processing` docs become `failed` on startup. Replace assertion: now it must verify enqueue was called with `_job_id=f"ingest:{doc.id}"`, and the doc row is **unchanged** (still `processing`, chunks intact).

Example (full new test):

```python
@pytest.mark.asyncio
async def test_reaper_reenqueues_processing_docs_without_touching_state(db_session):
    """Reaper enqueues with deterministic _job_id; doc state and chunks
    are NOT touched (the worker's step-1 owns cleanup)."""
    from sqlalchemy import insert
    from src.models.schemas import Document, DocumentChunk, DocumentStatus, User, Session as SessionRow
    from src.api.reaper import reenqueue_processing_documents
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    user_id = uuid4()
    sess_id = uuid4()
    doc_id = uuid4()
    await db_session.execute(insert(User).values(id=user_id, name="t"))
    await db_session.execute(insert(SessionRow).values(id=sess_id, user_id=user_id))
    await db_session.execute(insert(Document).values(
        id=doc_id, user_id=user_id, session_id=sess_id, filename="x.pdf",
        page_count=10, byte_size=1000, status=DocumentStatus.processing,
        progress_page=42,
    ))
    await db_session.execute(insert(DocumentChunk).values(
        id=uuid4(), document_id=doc_id, page_no=1, chunk_idx=0,
        content="leftover", content_embedding=[0.0]*1024, token_count=8,
    ))
    await db_session.commit()

    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=MagicMock())

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.db.session import get_engine
    sm = async_sessionmaker(get_engine(), expire_on_commit=False)

    await reenqueue_processing_documents(arq_pool=fake_pool, sessionmaker=sm)

    fake_pool.enqueue_job.assert_awaited_once()
    args, kwargs = fake_pool.enqueue_job.call_args
    assert args == ("ingest_document", str(doc_id))
    assert kwargs == {"_job_id": f"ingest:{doc_id}"}

    # Doc state untouched
    from sqlalchemy import select
    row = (await db_session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
    assert row.status == DocumentStatus.processing
    assert row.progress_page == 42
    chunk_count = (await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )).scalars().all()
    assert len(chunk_count) == 1
```

Delete the older test that asserted `status=failed` post-cleanup.

- [ ] **Step 12.2: Run to verify it fails**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py -v
```

Expected: FAIL — `src.api.reaper` doesn't exist.

- [ ] **Step 12.3: Implement `src/api/reaper.py`**

Create:

```python
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
```

- [ ] **Step 12.4: Wire reaper into `src/main.py`**

Replace the existing `_cleanup_stale_documents_on_startup` block in `make_app_default()`:

```python
    @app.on_event("startup")
    async def _reenqueue_processing_on_startup():
        from src.api.reaper import reenqueue_processing_documents
        # Pool may not be ready yet on first startup tick; arq pool's
        # startup runs in a separate hook (Task 10), so register this
        # AFTER that hook in source order to guarantee ordering.
        await reenqueue_processing_documents(
            arq_pool=app.state.arq_pool,
            sessionmaker=deps.sessionmaker,
        )
```

Move this hook so it lives **after** the `_create_arq_pool` hook.

- [ ] **Step 12.5: Remove `cleanup_stale_documents` from `src/ingest/ingestion.py`**

Delete the function (lines 114-131 originally). Also remove the now-unused `from sqlalchemy import select` and `from src.models.schemas import Document` if they only existed for that function.

- [ ] **Step 12.6: Run tests**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_startup_recovery.py -v
```

Expected: PASS.

- [ ] **Step 12.7: Commit**

```bash
git add src/api/reaper.py src/main.py src/ingest/ingestion.py tests/unit/test_startup_recovery.py
git commit -m "feat(reaper): rewrite startup hook to enqueue with _job_id (no state mutation)"
```

---

## Phase 5 — Integration tests + cleanup

### Task 13: docker-compose.test.yml + e2e happy path

**Files:**
- Create: `docker-compose.test.yml`
- Create: `tests/e2e/test_worker_e2e.py`

- [ ] **Step 13.1: Create test compose file**

`docker-compose.test.yml`:

```yaml
services:
  postgres-test:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: docqa_test
    ports: ["55432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d docqa_test"]
      interval: 2s
      timeout: 2s
      retries: 10

  redis-test:
    image: redis:7-alpine
    ports: ["56379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 10
```

- [ ] **Step 13.2: Write happy-path e2e test**

Create `tests/e2e/test_worker_e2e.py`:

```python
"""End-to-end worker tests with real redis + postgres.

Prerequisites: `docker compose -f docker-compose.test.yml up -d` so
postgres-test (5532) and redis-test (6379) are reachable.
"""
import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from arq.worker import Worker
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.models.schemas import Document, DocumentChunk, DocumentStatus, Session as SessionRow, User
from src.worker.jobs import INGEST_MAX_TRIES, INGEST_TIMEOUT, ingest_document
from src.worker.redis_pool import make_redis_settings

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:55432/docqa_test"
os.environ["REDIS_URL"] = "redis://localhost:56379/0"

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(os.environ["DATABASE_URL"])
    # Apply migrations once per session
    import subprocess
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                    env={**os.environ}, check=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sm(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_embedder():
    e = MagicMock()
    async def fake_embed(texts):
        return [[0.01 * i] * 1024 for i in range(len(texts))]
    e.embed_batch_async = fake_embed
    e.encode_one_async = lambda t: [0.0] * 1024
    return e


@pytest_asyncio.fixture
async def seeded_doc(sm, tmp_path):
    """Insert a User+Session+Document and place a real PDF on disk."""
    uploads = Path("data/uploads")
    uploads.mkdir(parents=True, exist_ok=True)

    doc_id = uuid4()
    target = uploads / f"{doc_id}.pdf"
    target.write_bytes(FIXTURE.read_bytes())

    user_id = uuid4()
    sess_id = uuid4()
    async with sm() as db:
        await db.execute(insert(User).values(id=user_id, name="t"))
        await db.execute(insert(SessionRow).values(id=sess_id, user_id=user_id))
        await db.execute(insert(Document).values(
            id=doc_id, user_id=user_id, session_id=sess_id, filename="t.pdf",
            page_count=3, byte_size=target.stat().st_size,
            status=DocumentStatus.processing, progress_page=0,
        ))
        await db.commit()
    yield doc_id, sm
    target.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_worker_e2e_happy_path(seeded_doc, fake_embedder):
    doc_id, sm = seeded_doc

    # Enqueue via real arq pool
    from arq import create_pool
    pool = await create_pool(make_redis_settings())
    job = await pool.enqueue_job(
        "ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}",
    )
    assert job is not None

    # Spin up an in-process worker; burst=True makes it exit when queue is drained
    from arq.worker import func
    worker = Worker(
        functions=[func(ingest_document, name="ingest_document",
                        timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES)],
        redis_settings=make_redis_settings(),
        burst=True,
        max_jobs=1,
        ctx={"sessionmaker": sm, "embedder": fake_embedder},
    )
    await worker.async_run()
    await pool.aclose()

    # Verify terminal state
    from sqlalchemy import select
    async with sm() as db:
        doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
        assert doc.status == DocumentStatus.ready
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )).scalars().all()
        assert len(chunks) > 0
        assert all(len(c.content_embedding) == 1024 for c in chunks)
```

- [ ] **Step 13.3: Bring up test stack and run**

```bash
docker compose -f docker-compose.test.yml up -d
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-test:5432/docqa_test -e REDIS_URL=redis://redis-test:6379/0 backend uv run pytest tests/e2e/test_worker_e2e.py::test_worker_e2e_happy_path -v
```

Expected: PASS. (Adjust hostnames in the env vars if you run pytest from host vs in-container.)

- [ ] **Step 13.4: Commit**

```bash
git add docker-compose.test.yml tests/e2e/test_worker_e2e.py
git commit -m "test(worker): e2e happy path with real redis + postgres"
```

---

### Task 14: e2e fault injection — three scenarios

**Files:**
- Modify: `tests/e2e/test_worker_e2e.py`

- [ ] **Step 14.1: Add worker-crash test**

Append to `tests/e2e/test_worker_e2e.py`:

```python
@pytest.mark.asyncio
async def test_worker_crash_midjob_recovers_on_reenqueue(seeded_doc, fake_embedder):
    """First worker crashes mid-ingestion; second worker picks the same
    job_id back up via Arq lease expiry + step-1 idempotent reset → end
    state is `ready` with the right chunk count."""
    doc_id, sm = seeded_doc

    # First run: monkeypatch _ingest_document inside the worker's view
    # so it crashes after writing a few chunks.
    crash_after_pages = 1
    seen_pages = []

    async def crashing_ingest(doc_id_arg, *, path, mem, embedder, iter_pages, chunker):
        from src.ingest.ingestion import _ingest_document
        # Wrap iter_pages to crash after N pages
        original = iter_pages
        def limited(p):
            for i, page in enumerate(original(p)):
                if i >= crash_after_pages:
                    raise RuntimeError("simulated crash")
                seen_pages.append(i)
                yield page
        await _ingest_document(doc_id_arg, path=path, mem=mem, embedder=embedder,
                                iter_pages=limited, chunker=chunker)

    import src.worker.jobs as jobs
    real_ingest = jobs._ingest_document
    jobs._ingest_document = crashing_ingest

    from arq import create_pool
    from arq.worker import Worker, func
    pool = await create_pool(make_redis_settings())
    await pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")

    worker1 = Worker(
        functions=[func(ingest_document, name="ingest_document",
                        timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES)],
        redis_settings=make_redis_settings(), burst=True, max_jobs=1,
        ctx={"sessionmaker": sm, "embedder": fake_embedder},
    )
    await worker1.async_run()  # crashes the job

    # Restore real _ingest_document; re-enqueue (simulates reaper)
    jobs._ingest_document = real_ingest
    await pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")

    worker2 = Worker(
        functions=[func(ingest_document, name="ingest_document",
                        timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES)],
        redis_settings=make_redis_settings(), burst=True, max_jobs=1,
        ctx={"sessionmaker": sm, "embedder": fake_embedder},
    )
    await worker2.async_run()
    await pool.aclose()

    from sqlalchemy import select
    async with sm() as db:
        doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
        assert doc.status == DocumentStatus.ready
        chunks = (await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )).scalars().all()
        # Critical: chunks count == full ingestion's count, not crashed-run leftover
        assert len(chunks) >= 1
```

- [ ] **Step 14.2: Add `_job_id` dedup test**

Append:

```python
@pytest.mark.asyncio
async def test_job_id_dedup_prevents_duplicate_enqueue(seeded_doc, fake_embedder):
    """Three rapid enqueues with the same _job_id must coalesce to one
    in-flight job."""
    doc_id, sm = seeded_doc
    from arq import create_pool
    pool = await create_pool(make_redis_settings())
    j1 = await pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")
    j2 = await pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")
    j3 = await pool.enqueue_job("ingest_document", str(doc_id), _job_id=f"ingest:{doc_id}")
    assert j1 is not None
    assert j2 is None
    assert j3 is None
    await pool.aclose()
```

- [ ] **Step 14.3: Run all e2e tests**

```bash
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-test:5432/docqa_test -e REDIS_URL=redis://redis-test:6379/0 backend uv run pytest tests/e2e/test_worker_e2e.py -v
```

Expected: 3 PASS.

- [ ] **Step 14.4: Commit**

```bash
git add tests/e2e/test_worker_e2e.py
git commit -m "test(worker): fault injection — crash recovery + job_id dedup"
```

---

### Task 15: Static-grep guard — no sync embedder calls in async paths

**Files:**
- Create: `tests/unit/test_no_sync_embedder_in_async_paths.py`

- [ ] **Step 15.1: Write the guard test**

Create `tests/unit/test_no_sync_embedder_in_async_paths.py`:

```python
"""Static guard: in async ingestion / chat / search paths, BGE encode
must go through the *_async methods. Bare embedder.embed_batch /
encode_one calls would silently re-block the event loop."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
ASYNC_FILES = [
    ROOT / "src/ingest/ingestion.py",
    ROOT / "src/api/chat.py",
    ROOT / "src/tools/search_documents.py",
    ROOT / "src/worker/jobs.py",
]
# Match `embedder.embed_batch(`, `.encode_one(`, `.embed(` not followed by
# `_async` and not a method definition.
SYNC_CALL = re.compile(
    r"\b(embedder|self\.embedder)\.(embed_batch|encode_one|embed)\("
)


@pytest.mark.parametrize("path", ASYNC_FILES, ids=lambda p: p.name)
def test_no_sync_embedder_calls(path: Path):
    text = path.read_text()
    matches = []
    for line_no, line in enumerate(text.splitlines(), 1):
        # Skip comments/docstrings
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        if SYNC_CALL.search(line):
            matches.append(f"{path.name}:{line_no}: {line.strip()}")
    assert not matches, "Sync embedder API used in async path:\n" + "\n".join(matches)
```

- [ ] **Step 15.2: Run the guard**

```bash
docker compose exec -T backend uv run pytest tests/unit/test_no_sync_embedder_in_async_paths.py -v
```

Expected: PASS for all 4 files.

- [ ] **Step 15.3: Commit**

```bash
git add tests/unit/test_no_sync_embedder_in_async_paths.py
git commit -m "test: forbid sync BGE calls in async ingestion/chat paths"
```

---

### Task 16: Manual smoke + dead-code removal

**Files:**
- Modify: `src/ingest/ingestion.py` — remove `_ingest_with_timeout`

- [ ] **Step 16.1: Manual smoke test (no test file — interactive)**

```bash
./dev.sh down
./dev.sh -d
docker compose ps  # 4 services healthy
```

Open `http://localhost:3000`, upload `腾讯2025年度报告.pdf`. While ingestion runs:

1. Watch `docker compose logs worker --since=2m -f` — you should see `event=ingest.start ...`, periodic `event=ingest.reset ...`, and eventually `event=ingest.ready ...`
2. While encode is running, open a new chat and send a message. Verify the response comes back fluidly (event loop free).
3. After it succeeds, refresh the document list. Status `ready`.

If anything fails, capture the relevant log lines and stop here — do not commit dead-code removal yet.

- [ ] **Step 16.2: Remove `_ingest_with_timeout`**

Delete the function from `src/ingest/ingestion.py` (lines starting `async def _ingest_with_timeout(...)` through its closing). Remove the now-unused `import asyncio` only if no other reference remains.

Also delete its only remaining importer: `src/api/documents.py:15 from src.ingest.ingestion import _ingest_with_timeout` (replaced by enqueue path in Task 11; the import should already be gone, double-check).

- [ ] **Step 16.3: Run the full suite**

```bash
docker compose exec -T backend uv run pytest tests/ -v
docker compose exec -T -e DATABASE_URL=... -e REDIS_URL=... backend uv run pytest tests/e2e/ -v
```

Expected: all PASS.

- [ ] **Step 16.4: Commit**

```bash
git add src/ingest/ingestion.py src/api/documents.py
git commit -m "chore: remove _ingest_with_timeout (replaced by arq func timeout)"
```

---

### Task 17: Tear down test stack

- [ ] **Step 17.1: Stop test compose stack**

```bash
docker compose -f docker-compose.test.yml down -v
```

- [ ] **Step 17.2: Open PR**

```bash
git push -u origin fix/ingestion-race-and-progress
gh pr create --title "Move ingestion to dedicated arq worker container" --body "$(cat <<'EOF'
## Summary
- BGE encode now runs in a per-process single-thread executor; chat is no longer blocked during ingestion.
- Ingestion runs in a new `worker` Docker service consuming jobs from a new `redis` broker via Arq 0.28.
- Backend uses deterministic `_job_id=ingest:{doc_id}` for dedup; reaper on startup re-enqueues stale `processing` docs without mutating state (worker step-1 owns idempotent cleanup).
- Last-try cancellation marks the doc `failed` via a fresh session so the user can delete and retry.
- Business vs infra exception split: PDF-content failures mark `failed`; DB / network blips propagate to Arq for retry within `max_tries=2`.
- Spec: `docs/superpowers/specs/2026-04-26-ingestion-worker-design.md`

## Test plan
- [x] `pytest tests/unit -v` (all green)
- [x] `pytest tests/e2e -v` against `docker-compose.test.yml`
- [x] Manual: upload 282-page PDF; chat remains responsive throughout
- [x] Manual: kill worker mid-ingest, restart; doc reaches `ready` after re-run
EOF
)"
```

---

## Self-Review Checklist (executed by plan author)

**1. Spec coverage:**

- §3.1 backend changes → Tasks 11, 12 ✓
- §3.2 worker structure (constants, on_startup, on_shutdown, job, INGEST_MAX_TRIES, CancelledError handler) → Tasks 5-8 ✓
- §3.3 redis container → Task 9 ✓
- §3.4 schema (no migration) → covered by absence of migration tasks ✓
- §3.5 BgeEmbedder executor + close + lifecycle wiring → Tasks 1, 2, 8 (worker on_shutdown) ✓
- §4.1 upload flow with rename-before-enqueue → Task 11 (step 11.3 explicit) ✓
- §4.2 worker consume flow with file preflight + async embed_batch_async → Tasks 6, 3 ✓
- §4.3 SSE unchanged → no task needed ✓
- §5.1 exception classification → Task 4 ✓
- §5.2 cancel handling (last-try) → Task 7 ✓
- §5.3 reaper rewrite → Task 12 ✓
- §5.4 Redis-down on upload → Task 11 (test_upload_handles_redis_failure_returns_503) ✓
- §6 deps + compose → Task 9 ✓
- §7.1 unit tests → Tasks 1, 4, 6, 7, 12, 15 ✓
- §7.2 integration → Task 13 ✓
- §7.3 fault injection → Task 14 ✓
- §8 structured logging → Task 11 (event=ingest.enqueue), Task 6 (start/reset/business), Task 7 (cancelled), Task 12 (reaper.scan/enqueue) ✓
- §10 decisions captured implicitly via implementation ✓
- §11 risks documented in spec; no implementation tasks needed ✓

**2. Placeholder scan:** No "TBD", "TODO", "implement later" outside of one explicit fixture-version note in Task 10.1; that's a known fragility flagged for the implementer to adjust. All other steps include concrete code.

**3. Type/name consistency:**
- `INGEST_MAX_TRIES` / `INGEST_TIMEOUT` consistent across Tasks 5, 6, 7, 8, 13, 14 ✓
- `embed_batch_async` / `encode_one_async` consistent ✓
- `_job_id=f"ingest:{doc_id}"` consistent across Tasks 11, 12, 14 ✓
- `reenqueue_processing_documents` consistent across Task 12 ✓
