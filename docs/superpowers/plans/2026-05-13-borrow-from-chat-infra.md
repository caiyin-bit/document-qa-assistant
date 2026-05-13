# Borrow-from-Chat Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the four P0 infra patterns + the P1 routing audit field from sister project `chat` into `doc-qa`, per `docs/borrow-from-chat-checklist.md`.

**Architecture:**
- Five independent infra changes (each lands and ships on its own): generalized RRF helper, tool registry DI refactor, prompt-template tool-rules extraction, retrieval evaluation harness, and `messages.routing` JSONB audit field.
- All changes are additive to the existing pipeline — no behavior change for end users until each is wired into a feature.
- TDD throughout: every code change starts with a failing unit test.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 (async) + Alembic, asyncpg, pgvector + pg_trgm, BGE embeddings, pytest + pytest-asyncio, testcontainers-postgres.

---

## State of the World (verified 2026-05-13)

Verified before drafting this plan:

| Borrow item | doc-qa current state | Action |
|---|---|---|
| P0.1 RRF helper | `search_chunks_hybrid` at `src/core/memory_service.py:374-421` already does RRF inline; **no** `_rrf_fuse_scores` helper, **no** stage-internal dedup, **no** explicit tiebreak. | Extract + harden. |
| P0.2 ToolRegistry | `src/core/tool_registry.py` (31 lines) already has try/except + unknown-tool branch; constructor hard-codes a single tool. Error shape is `{ok, error}` only — no structured `error` code + `message`. | Refactor to DI pattern + structured envelope. |
| P0.3 Persona split | `persona/IDENTITY.md` (15 lines) + `persona/SOUL.md` (8 lines) **already exist** with `src/core/persona_loader.py` (25 lines). | **Skip split.** Only extract tool-usage rules from `_A_TEMPLATE` into a swappable block. |
| P0.4 Eval script | No `scripts/eval_retrieval.py`. No `tests/fixtures/retrieval_eval.yaml`. | Build from scratch. |
| P1.1 routing column | `Message` has `citations` JSONB, no `routing` column. Latest migration is `0005_user_auth`. | Add migration `0006_messages_routing` + plumb through `conversation_engine.handle_stream`. |
| P1.2 Recall protocol | Pure design pattern; nothing to wire today. | Capture as a design note for future tool authors. |

---

## File Structure

**New files:**
- `tests/unit/test_memory_service_rrf.py` — RRF helper unit tests
- `tests/unit/test_tool_registry.py` — ToolRegistry behavioral tests
- `tests/fixtures/retrieval_eval.yaml` — eval fixture (documents + queries + expected hits)
- `scripts/eval_retrieval.py` — eval driver
- `src/db/migrations/versions/0006_messages_routing.py` — Alembic migration
- `docs/design/recall-tool-protocol.md` — design note (P1.2)

**Modified files:**
- `src/core/memory_service.py` — add `_rrf_fuse_scores` helper; refactor `search_chunks_hybrid` to use it
- `src/core/tool_registry.py` — DI constructor + `default()` factory + structured error envelope
- `src/core/conversation_engine.py` — pass `routing` dict to `save_assistant_message`
- `src/core/prompt_templates.py` — extract `_TOOL_USAGE_RULES` constant from `_A_TEMPLATE`
- `src/tools/search_documents.py` — match new error envelope shape
- `src/models/schemas.py` — add `Message.routing` field
- `tests/unit/test_prompt_templates.py` — assert tool-rules block is present

---

# Group A — P0.1: Generalized RRF Helper

### Task A.1: Add `_rrf_fuse_scores` helper to memory_service

**Files:**
- Modify: `src/core/memory_service.py` (top of file, before the class)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_memory_service_rrf.py`:

```python
"""Unit tests for RRF fusion helper."""
from __future__ import annotations

import pytest

from src.core.memory_service import _rrf_fuse_scores


def test_rrf_simple_two_stages():
    stage_a = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    stage_b = [{"chunk_id": "b"}, {"chunk_id": "d"}, {"chunk_id": "a"}]
    scores = _rrf_fuse_scores([stage_a, stage_b], k=60)
    assert pytest.approx(scores["a"], rel=1e-9) == 1 / 61 + 1 / 63
    assert pytest.approx(scores["b"], rel=1e-9) == 1 / 62 + 1 / 61
    assert pytest.approx(scores["c"], rel=1e-9) == 1 / 63
    assert pytest.approx(scores["d"], rel=1e-9) == 1 / 62


def test_rrf_dedups_within_stage():
    """Same chunk appearing twice in one stage contributes only its best rank."""
    duped = [{"chunk_id": "a"}, {"chunk_id": "a"}, {"chunk_id": "b"}]
    scores = _rrf_fuse_scores([duped], k=60)
    assert pytest.approx(scores["a"], rel=1e-9) == 1 / 61
    # rank slot 2 belongs to the dup'd 'a' and is skipped; 'b' is rank 3
    assert pytest.approx(scores["b"], rel=1e-9) == 1 / 63


def test_rrf_caller_sorts_with_id_tiebreak():
    """When two chunks tie on score, caller's (score DESC, id ASC) sort wins."""
    stage_a = [{"chunk_id": "z"}, {"chunk_id": "a"}]
    stage_b = [{"chunk_id": "a"}, {"chunk_id": "z"}]
    scores = _rrf_fuse_scores([stage_a, stage_b], k=60)
    fused = sorted(scores, key=lambda cid: (-scores[cid], cid))
    assert pytest.approx(scores["a"], rel=1e-9) == scores["z"]
    assert fused == ["a", "z"]


def test_rrf_empty_input_returns_empty_dict():
    assert _rrf_fuse_scores([], k=60) == {}
    assert _rrf_fuse_scores([[], []], k=60) == {}


def test_rrf_three_stages_generalization():
    s1 = [{"chunk_id": "x"}]
    s2 = [{"chunk_id": "y"}]
    s3 = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    scores = _rrf_fuse_scores([s1, s2, s3], k=60)
    assert pytest.approx(scores["x"], rel=1e-9) == 1 / 61 + 1 / 61
    assert pytest.approx(scores["y"], rel=1e-9) == 1 / 61 + 1 / 62
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_service_rrf.py -v`
Expected: FAIL with `ImportError: cannot import name '_rrf_fuse_scores'`.

- [ ] **Step 3: Add the helper at the top of `src/core/memory_service.py`**

After the existing imports (current line 11), insert:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_memory_service_rrf.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/core/memory_service.py tests/unit/test_memory_service_rrf.py
git commit -m "feat(rrf): add generalized _rrf_fuse_scores helper with stage dedup"
```

---

### Task A.2: Rewire `search_chunks_hybrid` to use the helper + explicit tiebreak

**Files:**
- Modify: `src/core/memory_service.py:374-421` (the `search_chunks_hybrid` method)

- [ ] **Step 1: Add a test that asserts deterministic ordering under a tie**

Append to `tests/unit/test_memory_service_rrf.py`:

```python
def test_hybrid_uses_helper_and_tiebreaks_by_chunk_id(monkeypatch):
    """search_chunks_hybrid must call _rrf_fuse_scores and tiebreak by chunk_id ASC."""
    import asyncio
    from src.core.memory_service import MemoryService

    svc = MemoryService.__new__(MemoryService)  # bypass __init__
    svc.db = None  # not used by the patched methods

    # Both stages return the same chunks at swapped ranks → identical fused scores.
    stage_vec = [
        {"chunk_id": "zzzz", "doc_id": "d1", "filename": "f", "page_no": 1, "content": "...", "score": 0.9},
        {"chunk_id": "aaaa", "doc_id": "d1", "filename": "f", "page_no": 2, "content": "...", "score": 0.8},
    ]
    stage_kw = [
        {"chunk_id": "aaaa", "doc_id": "d1", "filename": "f", "page_no": 2, "content": "...", "score": 0.9},
        {"chunk_id": "zzzz", "doc_id": "d1", "filename": "f", "page_no": 1, "content": "...", "score": 0.8},
    ]

    async def fake_vec(*args, **kwargs): return stage_vec
    async def fake_kw(*args, **kwargs): return stage_kw

    monkeypatch.setattr(svc, "search_chunks", fake_vec)
    monkeypatch.setattr(svc, "search_chunks_keyword", fake_kw)

    out = asyncio.run(svc.search_chunks_hybrid(
        session_id="00000000-0000-0000-0000-000000000000",
        query="x", query_embedding=[0.0] * 1024,
        top_k=2, min_similarity=0.0,
    ))
    # Both chunks tie on RRF score; "aaaa" < "zzzz" lexicographically.
    assert [r["chunk_id"] for r in out] == ["aaaa", "zzzz"]
    # Score is the RRF score, not the per-stage similarity.
    assert out[0]["score"] == pytest.approx(1 / 61 + 1 / 62, rel=1e-9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_service_rrf.py::test_hybrid_uses_helper_and_tiebreaks_by_chunk_id -v`
Expected: FAIL — current implementation's ordering is not guaranteed under ties.

- [ ] **Step 3: Replace the body of `search_chunks_hybrid`**

In `src/core/memory_service.py`, replace lines 374-421 with:

```python
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
```

- [ ] **Step 4: Run the new test plus the full memory_service suite**

Run: `pytest tests/unit/test_memory_service_rrf.py tests/unit/test_memory_service.py tests/unit/test_search_documents.py -v`
Expected: all pass. If `test_search_documents.py::test_uses_hybrid_when_memory_supports_it` checks the hybrid call, ensure it still passes — the public signature is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/core/memory_service.py tests/unit/test_memory_service_rrf.py
git commit -m "refactor(rrf): use _rrf_fuse_scores helper + explicit chunk_id tiebreak"
```

---

# Group B — P0.2: ToolRegistry DI Pattern + Structured Errors

### Task B.1: Refactor `ToolRegistry` constructor to accept a tools dict

**Files:**
- Modify: `src/core/tool_registry.py` (full replacement)
- Modify: anywhere `ToolRegistry(...)` is instantiated (verify via grep below)

- [ ] **Step 1: Find every instantiation site**

Run: `grep -rn "ToolRegistry(" src/ tests/ scripts/`
Expected output should be small (likely just one app wiring location + maybe a test). Record the lines that need updating.

- [ ] **Step 2: Write failing tests for the new structure**

Create `tests/unit/test_tool_registry.py`:

```python
"""ToolRegistry behavioral tests: protocol/business/system error layers."""
from __future__ import annotations

import pytest

from src.core.tool_registry import ToolRegistry


class _StubTool:
    def __init__(self, return_value=None, raise_exc=None):
        self.return_value = return_value
        self.raise_exc = raise_exc
        self.called_with = None

    async def execute(self, *, session_id, **kwargs):
        self.called_with = {"session_id": session_id, **kwargs}
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_value


@pytest.mark.asyncio
async def test_schemas_wraps_each_schema_in_function_envelope():
    schema = {"name": "do_thing", "description": "x", "parameters": {}}
    reg = ToolRegistry({"do_thing": (schema, _StubTool())})
    assert reg.schemas() == [{"type": "function", "function": schema}]


@pytest.mark.asyncio
async def test_execute_dispatches_by_name_and_passes_session_id():
    tool = _StubTool(return_value={"ok": True, "answer": 42})
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, tool)})
    out = await reg.execute("do_thing", {"q": "hi"}, session_id="sess-1")
    assert out == {"ok": True, "answer": 42}
    assert tool.called_with == {"session_id": "sess-1", "q": "hi"}


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_structured_protocol_error():
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, _StubTool())})
    out = await reg.execute("missing_tool", {}, session_id="s")
    assert out == {
        "ok": False, "error": "unknown_tool",
        "message": "unknown tool: missing_tool",
    }


@pytest.mark.asyncio
async def test_execute_tool_exception_returns_structured_system_error():
    tool = _StubTool(raise_exc=RuntimeError("db connection lost"))
    reg = ToolRegistry({"do_thing": ({"name": "do_thing"}, tool)})
    out = await reg.execute("do_thing", {}, session_id="s")
    assert out["ok"] is False
    assert out["error"] == "system"
    assert "db connection lost" in out["message"]


@pytest.mark.asyncio
async def test_default_factory_wires_search_documents():
    """The default factory should produce a working registry for the V1 toolset."""
    from src.tools.search_documents import TOOL_SCHEMA

    class _FakeMem:
        async def search_chunks_hybrid(self, *a, **k): return []
        async def search_chunks(self, *a, **k): return []
    class _FakeEmbedder:
        async def encode_one_async(self, q): return [0.0] * 1024

    reg = ToolRegistry.default(
        mem=_FakeMem(), embedder=_FakeEmbedder(),
        min_similarity=0.5, top_k=20, reranker=None, rerank_top_n=5,
    )
    schemas = reg.schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == TOOL_SCHEMA["name"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_registry.py -v`
Expected: ALL FAIL — current `ToolRegistry.__init__` takes kwargs, not a tools dict.

- [ ] **Step 4: Replace `src/core/tool_registry.py` with the new structure**

Full new content:

```python
"""Tool registry — name → (schema, tool instance) DI pattern.

Three error layers (chat-borrowed):
  1. Protocol error  — caller asked for an unknown tool name. Returned
     by `execute()` before any tool code runs.
  2. Business error  — tool's own validation/lookup failure. Tools return
     `{ok: False, error: "<code>", message: "..."}` themselves.
  3. System error    — tool raised an unhandled exception. Caught here
     so a failing tool can't crash the assistant loop.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from src.tools.search_documents import SearchDocumentsTool, TOOL_SCHEMA

log = logging.getLogger(__name__)


class _ToolLike(Protocol):
    async def execute(self, *, session_id: Any, **kwargs: Any) -> dict: ...


ToolEntry = tuple[dict, _ToolLike]


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolEntry]) -> None:
        self._tools = tools

    @classmethod
    def default(
        cls, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
    ) -> "ToolRegistry":
        """V1 wiring: only search_documents.

        Add new tools here as the V2 surface grows. Each entry is
        (raw_schema_dict, tool_instance).
        """
        return cls({
            "search_documents": (
                TOOL_SCHEMA,
                SearchDocumentsTool(
                    mem=mem, embedder=embedder,
                    min_similarity=min_similarity, top_k=top_k,
                    reranker=reranker, rerank_top_n=rerank_top_n,
                ),
            ),
        })

    def schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas wrapped in OpenAI Tools API envelope.

        Some strict gateways (we hit this on a previous SiliconFlow
        deployment) reject calls missing the {type, function} wrapper
        with 400 "Field required". Keep the wrapper unconditionally.
        """
        return [
            {"type": "function", "function": schema}
            for schema, _ in self._tools.values()
        ]

    async def execute(
        self, name: str, arguments: dict, *, session_id,
    ) -> dict:
        entry = self._tools.get(name)
        if not entry:
            log.warning("tool_registry.unknown name=%s", name)
            return {
                "ok": False, "error": "unknown_tool",
                "message": f"unknown tool: {name}",
            }
        _, tool = entry
        try:
            return await tool.execute(session_id=session_id, **arguments)
        except Exception as e:
            log.exception("tool_registry.system_error name=%s", name)
            return {
                "ok": False, "error": "system",
                "message": str(e)[:200],
            }
```

- [ ] **Step 5: Update every instantiation site found in Step 1**

Replace `ToolRegistry(mem=..., embedder=..., ...)` with `ToolRegistry.default(mem=..., embedder=..., ...)`.

Likely site: app startup / dependency wiring (search for `ToolRegistry(`). Apply the rename.

- [ ] **Step 6: Run the new tests + the existing search_documents tests**

Run: `pytest tests/unit/test_tool_registry.py tests/unit/test_search_documents.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/core/tool_registry.py tests/unit/test_tool_registry.py
# plus any modified wiring files
git commit -m "refactor(tools): ToolRegistry DI + structured 3-layer error envelope"
```

---

### Task B.2: Align `search_documents` error envelope with the registry contract

**Files:**
- Modify: `src/tools/search_documents.py`

- [ ] **Step 1: Audit current error returns**

Run: `grep -n '"ok":' src/tools/search_documents.py`

Note every `{"ok": False, ...}` return. We want each to carry an `error` code (machine-readable) and a `message` (human-readable), matching the registry's protocol/system envelope. Existing returns shaped `{"ok": False, "error": "..."}` should be reshaped to `{"ok": False, "error": "<code>", "message": "..."}`.

- [ ] **Step 2: Write a failing test for the envelope shape**

Append to `tests/unit/test_search_documents.py`:

```python
@pytest.mark.asyncio
async def test_envelope_shape_on_business_error(monkeypatch):
    """All non-OK returns must carry error + message keys."""
    from src.tools.search_documents import SearchDocumentsTool

    class _Mem:
        async def search_chunks_hybrid(self, *a, **k): raise ValueError("boom")
        async def search_chunks(self, *a, **k): raise ValueError("boom")
    class _Emb:
        async def encode_one_async(self, q): return [0.0] * 1024

    tool = SearchDocumentsTool(
        mem=_Mem(), embedder=_Emb(),
        min_similarity=0.5, top_k=5, reranker=None, rerank_top_n=5,
    )
    # Wrapping with ToolRegistry would catch the exception — but if the tool
    # itself returns a structured error (e.g. for empty query), the envelope
    # must still be {ok:False, error:<code>, message:<str>}.
    out = await tool.execute(
        session_id="00000000-0000-0000-0000-000000000000",
        query="",
    )
    if out["ok"] is False:
        assert "error" in out and isinstance(out["error"], str)
        assert "message" in out and isinstance(out["message"], str)
```

- [ ] **Step 3: Run test to verify it fails OR passes trivially**

Run: `pytest tests/unit/test_search_documents.py::test_envelope_shape_on_business_error -v`

- If the current tool doesn't validate empty query, the test may pass trivially (returns `{ok: True, found: False}`). In that case, **leave the tool alone** — there are no business errors to reshape. Skip Step 4.
- If the tool returns a non-OK envelope without `message`, the test FAILS — proceed to Step 4.

- [ ] **Step 4: Reshape non-OK returns in `src/tools/search_documents.py`**

For every `return {"ok": False, ...}` in the file, ensure it carries both keys:

```python
# before
return {"ok": False, "error": "embedder unavailable"}
# after
return {"ok": False, "error": "embedder_unavailable",
        "message": "embedding service is offline"}
```

If no business-error returns exist (verified in Step 1), this task is a no-op — commit nothing.

- [ ] **Step 5: Run search_documents tests**

Run: `pytest tests/unit/test_search_documents.py -v`
Expected: all pass.

- [ ] **Step 6: Commit (only if changes were made)**

```bash
git add src/tools/search_documents.py tests/unit/test_search_documents.py
git commit -m "fix(tools): standardize search_documents error envelope to {error, message}"
```

---

# Group C — P0.3: Extract Tool-Usage Rules from Prompt Template

### Task C.1: Pull tool-usage rules out of `_A_TEMPLATE` into a dedicated constant

**Files:**
- Modify: `src/core/prompt_templates.py:28-69`
- Modify: `tests/unit/test_prompt_templates.py`

Context: `_A_TEMPLATE` currently bundles persona + scope + multi-search rule + reranker rule + no-match-fallback into one long template. Extracting the tool-usage portion makes it swappable when V2 adds new tools.

- [ ] **Step 1: Write a failing test asserting the rules block is a named, reusable constant**

Append to `tests/unit/test_prompt_templates.py`:

```python
def test_tool_usage_rules_block_is_exported_and_present_in_A():
    """The tool-usage rules must be a named constant and embedded in template A."""
    from src.core.prompt_templates import (
        _TOOL_USAGE_RULES, render_system_prompt,
    )

    # It's a non-trivial multi-line block of rules.
    assert "search_documents" in _TOOL_USAGE_RULES
    assert _TOOL_USAGE_RULES.count("\n") >= 5

    rendered = render_system_prompt(
        "A",
        docs=[{"filename": "test.pdf", "page_count": 3}],
        persona="P",
    )
    # The block appears verbatim in template-A output.
    assert _TOOL_USAGE_RULES.strip() in rendered


def test_tool_usage_rules_absent_from_B_templates():
    """B-EMPTY / B-PROCESSING must NOT mention the search tool."""
    from src.core.prompt_templates import render_system_prompt

    for tpl in ("B-EMPTY", "B-PROCESSING"):
        rendered = render_system_prompt(tpl, docs=[], persona="P")
        assert "search_documents" not in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_prompt_templates.py::test_tool_usage_rules_block_is_exported_and_present_in_A -v`
Expected: FAIL — `_TOOL_USAGE_RULES` does not exist yet.

- [ ] **Step 3: Edit `src/core/prompt_templates.py`**

Above `_A_TEMPLATE` (currently line 28), insert the new constant:

```python
# Tool-usage rules. Kept separate from _A_TEMPLATE so additional tools
# in V2 can append (or swap) the rule block without rewriting the whole
# template. Includes: multi-search mandate, query-construction hints,
# rerank guidance, and the final no-match fallback.
_TOOL_USAGE_RULES = """\
【最重要的规则——多组件问题必须发起多次 search】
如果用户问题里**列举了 ≥2 个独立子项**（例如同时问 总收入、收入成本、
销售开支、研发开支、净利润 这些不同字段），**禁止只搜 1 次就回答**。
你必须按子项分组发起 2-3 次 search_documents 调用，每次专门搜不同的
keyword。只有当 3 次 search 仍然找不到某个子项时，才允许在回答里说
"未在文档中找到 X 项"——但其它已搜到的子项必须正常呈现。

工作示例（用户问"瀑布图：总收入、收入成本、销售开支、行政开支、研发开支、净利润"）：
  第 1 次 search："总收入 营业收入 2025"
  第 2 次 search："收入成本 经营成本 销售成本"
  第 3 次 search："销售开支 一般行政开支 研发开支 净利润"
然后用三次 search 拼出的数字组合答案 + 输出图表。

【其它行为规则】
1. 任何用户问题都必须先调用 search_documents 工具检索
2. 构造检索 query 时**广撒网**，但**只展开核心概念**，不要带"报告期末"
   "截至 XX"这类财报通用模板词——它们在财报里出现频率太高，会把附注
   类无关页"霸榜"。
     用户问："期末员工总数是多少"
     好的 query："员工总数 雇员人数 员工数量 集团雇员"
     差的 query（带通用词反而稀释命中）："员工总数 雇员人数 报告期末 截至年底 十二月三十一日"
     差的 query（抄原话太窄）："期末员工总数"
   财报中常见核心同义（不限于此）：员工↔雇员；总数↔人数↔数量；
   营收↔总收入↔营业收入；净利润↔归母净利润；同比↔较去年。
3. 单组件问题第一次工具结果不直接命中答案时，可以换不同关键词再搜
   一次（工具最多自动循环 3 次）；不要因为"似乎没找到"就立刻放弃
4. 工具最终仍未返回任何相关 chunks 时（**所有** search 都返回空），
   才允许**完整、原样**回答：
   "{no_match}"
   不要补充猜测、不要解释为什么没找到、不要给替代答案
5. 工具返回 found=true 时，只能基于 chunks 内容作答；
   不得使用你的常识或训练知识补充
6. 不要在回答正文中标注 [1] [2] 这类引用，前端会自动渲染来源卡片
7. 用简洁、专业的中文回答；数字保留报告中的精度（包括单位"百万元"等）
"""
```

Then replace the existing `_A_TEMPLATE` body (lines 28-69) with:

```python
_A_TEMPLATE = """{persona}

你是一个文档问答助手。

【可用文档】
{doc_list}

{tool_usage_rules}
"""
```

And update `render_system_prompt` to inject the new field. Replace the `if template == "A":` branch:

```python
    if template == "A":
        doc_lines = "\n".join(
            f"- {d['filename']}（共 {d['page_count']} 页）" for d in docs
        ) or "（无）"
        return _A_TEMPLATE.format(
            persona=persona, doc_list=doc_lines,
            tool_usage_rules=_TOOL_USAGE_RULES.format(
                no_match=FIXED_RESPONSES["NO_MATCH"],
            ),
        ) + _STRUCTURED_OUTPUT_GUIDE
```

- [ ] **Step 4: Run the new tests + existing prompt tests**

Run: `pytest tests/unit/test_prompt_templates.py -v`
Expected: all pass. Spot-check: render `template="A"` with `persona="X"` and confirm the multi-search rule, the no-match fallback (with `NO_MATCH` text substituted), and the structured-output guide all still appear.

- [ ] **Step 5: Sanity check — render and eyeball**

```bash
python -c "from src.core.prompt_templates import render_system_prompt; print(render_system_prompt('A', docs=[{'filename':'x.pdf','page_count':1}], persona='persona-stub'))"
```

Expected: the output contains "在已上传文档中未找到相关信息" (the `NO_MATCH` text substituted into rule #4), the multi-search example, and the structured-output guide. No `{...}` placeholder strings should appear unsubstituted.

- [ ] **Step 6: Commit**

```bash
git add src/core/prompt_templates.py tests/unit/test_prompt_templates.py
git commit -m "refactor(prompt): extract _TOOL_USAGE_RULES from _A_TEMPLATE for tool-set swapping"
```

---

# Group D — P0.4: Retrieval Evaluation Harness

### Task D.1: Define the fixture YAML format

**Files:**
- Create: `tests/fixtures/retrieval_eval.yaml`

The eval needs deterministic content. Each fixture chunk is inserted directly into `document_chunks` with a pre-computed BGE embedding at eval time (not parsed from PDF), keeping the eval reproducible.

- [ ] **Step 1: Create the fixture file**

Create `tests/fixtures/retrieval_eval.yaml`:

```yaml
# Retrieval evaluation fixture. Hand-curated so chunk text overlaps with
# realistic query patterns (Chinese-financial-report domain). Each chunk
# is identified by `chunk_key` (deterministic, used in expected lists).
#
# How it's used: scripts/eval_retrieval.py creates one eval user + one
# session, inserts the documents below as `documents`, then chunks them
# directly into `document_chunks` (one chunk row per `chunks[]` entry),
# embedding the content with the live BGE embedder at run-time.

documents:
  - doc_key: doc_report_2025
    filename: "2025年年报.pdf"
    page_count: 4
    chunks:
      - chunk_key: report25_p1_employees
        page_no: 1
        content: "截至2025年12月31日，本集团雇员总数为115,849人。"
      - chunk_key: report25_p2_revenue
        page_no: 2
        content: "2025年全年总收入为人民币7,517亿元，同比增长13.9%。"
      - chunk_key: report25_p3_cost
        page_no: 3
        content: "2025年收入成本合计3,294亿元，毛利率约为56.2%。"
      - chunk_key: report25_p4_profit
        page_no: 4
        content: "归属于本公司股东的净利润达到1,946亿元，同比增长68.7%。"

  - doc_key: doc_report_2024
    filename: "2024年年报.pdf"
    page_count: 3
    chunks:
      - chunk_key: report24_p1_employees
        page_no: 1
        content: "截至2024年12月31日，集团雇员总数为110,558人，较上年增加3,720人。"
      - chunk_key: report24_p2_revenue
        page_no: 2
        content: "2024年全年总收入6,602亿元，同比增长8.4%。"
      - chunk_key: report24_p3_rd
        page_no: 3
        content: "2024年研发开支706亿元，占总收入比例10.7%。"

queries:
  - id: q_employees_25
    query: "员工总数 雇员人数 员工数量 集团雇员 2025"
    expected_chunk_keys: [report25_p1_employees]

  - id: q_revenue_25
    query: "总收入 营业收入 2025"
    expected_chunk_keys: [report25_p2_revenue]

  - id: q_cost_25
    query: "收入成本 经营成本 销售成本 毛利率"
    expected_chunk_keys: [report25_p3_cost]

  - id: q_profit_25
    query: "净利润 归母净利润 股东净利润 2025"
    expected_chunk_keys: [report25_p4_profit]

  - id: q_rd_24
    query: "研发开支 研发费用 研发投入 2024"
    expected_chunk_keys: [report24_p3_rd]

  - id: q_employees_24
    query: "员工总数 雇员人数 2024"
    expected_chunk_keys: [report24_p1_employees]
```

- [ ] **Step 2: Commit the fixture**

```bash
git add tests/fixtures/retrieval_eval.yaml
git commit -m "test(eval): add retrieval_eval fixture (2 docs, 7 chunks, 6 queries)"
```

---

### Task D.2: Build the eval driver script

**Files:**
- Create: `scripts/eval_retrieval.py`

Two surfaces × three modes form the eval matrix:

| | direct | tool |
|---|---|---|
| vector | `MemoryService.search_chunks(...)` | n/a (tool always hybrid) |
| trigram | `MemoryService.search_chunks_keyword(...)` | n/a |
| hybrid | `MemoryService.search_chunks_hybrid(...)` | `SearchDocumentsTool.execute(...)` |

For V1, run **direct × {vector, trigram, hybrid}** only. Skip the tool surface (it adds LLM reranker noise) — leave a TODO for V2.

- [ ] **Step 1: Write the script**

Create `scripts/eval_retrieval.py`:

```python
"""Retrieval evaluation harness.

Loads tests/fixtures/retrieval_eval.yaml, ingests fixture chunks into a
disposable session, runs the query set under three retrieval modes
(vector / trigram / hybrid), and prints R@1 / R@3 / R@5 / MRR per mode.
Optionally writes the metrics to a JSON baseline.

Usage:
  python scripts/eval_retrieval.py
  python scripts/eval_retrieval.py --modes vector hybrid
  python scripts/eval_retrieval.py --json eval_baseline.json
  python scripts/eval_retrieval.py --top-k 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.memory_service import MemoryService
from src.db.session import async_sessionmaker_  # adjust import to actual sessionmaker
from src.embedding.bge_embedder import BgeEmbedder  # adjust to actual class
from src.models.schemas import (
    Document, DocumentChunk, DocumentStatus, Session as DBSession,
    SessionDocument, User,
)

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "retrieval_eval.yaml"
EVAL_USER_EMAIL = "eval-bot@local"


async def _ensure_eval_user(db: AsyncSession) -> User:
    """Create-or-fetch a stable eval user; wiped each run."""
    from sqlalchemy import select, delete
    res = await db.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(id=uuid4(), email=EVAL_USER_EMAIL)  # adjust to your User init
        db.add(user)
        await db.flush()
    return user


async def _wipe_eval_data(db: AsyncSession, user_id) -> None:
    """Remove prior eval sessions/documents so reruns start clean."""
    from sqlalchemy import delete, select
    sids = (await db.execute(
        select(DBSession.id).where(DBSession.user_id == user_id)
    )).scalars().all()
    if sids:
        await db.execute(delete(SessionDocument).where(
            SessionDocument.session_id.in_(sids)))
        await db.execute(delete(Document).where(
            Document.session_id.in_(sids)))
        await db.execute(delete(DBSession).where(DBSession.id.in_(sids)))


async def _load_fixture(db: AsyncSession, embedder, user_id) -> tuple[str, dict[str, str]]:
    """Insert fixture documents + chunks, return (session_id, chunk_key→chunk_id)."""
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        fixture = yaml.safe_load(f)

    sess = DBSession(id=uuid4(), user_id=user_id)
    db.add(sess)
    await db.flush()

    chunk_key_to_id: dict[str, str] = {}
    for doc_spec in fixture["documents"]:
        doc = Document(
            id=uuid4(),
            user_id=user_id,
            session_id=sess.id,
            filename=doc_spec["filename"],
            page_count=doc_spec["page_count"],
            byte_size=0,
            status=DocumentStatus.ready,
        )
        db.add(doc)
        db.add(SessionDocument(session_id=sess.id, document_id=doc.id))
        await db.flush()

        for idx, c in enumerate(doc_spec["chunks"]):
            emb = await embedder.encode_one_async(c["content"])
            chunk = DocumentChunk(
                id=uuid4(),
                document_id=doc.id,
                page_no=c["page_no"],
                chunk_idx=idx,
                content=c["content"],
                content_embedding=emb,
                token_count=len(c["content"]),
            )
            db.add(chunk)
            await db.flush()
            chunk_key_to_id[c["chunk_key"]] = str(chunk.id)

    await db.commit()
    return str(sess.id), chunk_key_to_id


async def _run_one_query(
    mem: MemoryService, embedder, session_id, q: dict, mode: str, top_k: int,
) -> list[str]:
    """Return ranked chunk_id list for one query under one mode."""
    if mode == "vector":
        qvec = await embedder.encode_one_async(q["query"])
        hits = await mem.search_chunks(
            session_id, query_embedding=qvec, top_k=top_k, min_similarity=0.0,
        )
    elif mode == "trigram":
        hits = await mem.search_chunks_keyword(
            session_id, query=q["query"], top_k=top_k,
        )
    elif mode == "hybrid":
        qvec = await embedder.encode_one_async(q["query"])
        hits = await mem.search_chunks_hybrid(
            session_id, query=q["query"], query_embedding=qvec,
            top_k=top_k, min_similarity=0.0,
        )
    else:
        raise ValueError(f"unknown mode: {mode}")
    return [h["chunk_id"] for h in hits]


def _recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    if not expected:
        return 0.0
    return len(set(ranked[:k]) & expected) / len(expected)


def _mrr(ranked: list[str], expected: set[str]) -> float:
    for i, cid in enumerate(ranked, start=1):
        if cid in expected:
            return 1.0 / i
    return 0.0


async def main_async(args) -> int:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        fixture = yaml.safe_load(f)

    sessionmaker_ = async_sessionmaker_()  # adjust to your factory
    embedder = BgeEmbedder()                # adjust constructor as needed

    async with sessionmaker_() as db:
        user = await _ensure_eval_user(db)
        await _wipe_eval_data(db, user.id)
        await db.commit()

    async with sessionmaker_() as db:
        session_id, chunk_key_to_id = await _load_fixture(db, embedder, user.id)

    metrics: dict[str, dict] = {}
    async with sessionmaker_() as db:
        mem = MemoryService(db)
        for mode in args.modes:
            per_query = []
            for q in fixture["queries"]:
                expected_ids = {chunk_key_to_id[k] for k in q["expected_chunk_keys"]}
                ranked = await _run_one_query(
                    mem, embedder, session_id, q, mode, args.top_k,
                )
                per_query.append({
                    "id": q["id"],
                    "r@1": _recall_at_k(ranked, expected_ids, 1),
                    "r@3": _recall_at_k(ranked, expected_ids, 3),
                    "r@5": _recall_at_k(ranked, expected_ids, 5),
                    "mrr": _mrr(ranked, expected_ids),
                })
            metrics[mode] = {
                "per_query": per_query,
                "avg_r@1": statistics.mean(p["r@1"] for p in per_query),
                "avg_r@3": statistics.mean(p["r@3"] for p in per_query),
                "avg_r@5": statistics.mean(p["r@5"] for p in per_query),
                "avg_mrr": statistics.mean(p["mrr"] for p in per_query),
            }

    print(f"{'mode':<10} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'MRR':>6}")
    print("-" * 40)
    for mode, m in metrics.items():
        print(f"{mode:<10} {m['avg_r@1']:>6.3f} {m['avg_r@3']:>6.3f} "
              f"{m['avg_r@5']:>6.3f} {m['avg_mrr']:>6.3f}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "top_k": args.top_k,
                "metrics": metrics,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nbaseline written to {args.json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modes", nargs="+", default=["vector", "trigram", "hybrid"],
        choices=["vector", "trigram", "hybrid"],
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", type=str, default=None,
                        help="write JSON baseline to this path")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
```

**Note for implementer:** the imports `async_sessionmaker_`, `BgeEmbedder` are placeholders — match the actual project paths. Run `grep -rn "AsyncSession" src/ | head -5` and `grep -rn "class.*Embedder" src/embedding/` to find the right names. The `User(...)` constructor may need additional required fields (e.g. `password_hash`) — check `src/models/schemas.py` and supply dummies (eval user is not a login surface).

- [ ] **Step 2: Run the script against a real DB**

```bash
python scripts/eval_retrieval.py --json eval_baseline.json
```

Expected: a table printed with three rows (vector / trigram / hybrid) showing per-mode R@1/R@3/R@5/MRR. `hybrid` should equal or beat both component modes on average. If `hybrid < min(vector, trigram)`, investigate before continuing — likely the new `_rrf_fuse_scores` helper has a bug or the fixture queries don't exercise complementary recall.

- [ ] **Step 3: Sanity check the baseline JSON**

```bash
python -c "import json; m = json.load(open('eval_baseline.json'))['metrics']; print('vector R@1:', m['vector']['avg_r@1']); print('hybrid R@1:', m['hybrid']['avg_r@1'])"
```

Expected: numeric output. Both should be > 0 (small fixture, lots of overlap with query keywords).

- [ ] **Step 4: Add the baseline to the repo (or gitignore it)**

Decision point: check baseline JSON into `eval/` so PR reviewers can diff before/after, OR gitignore it and expect contributors to regenerate.

Recommendation: check it in at `eval/baseline_2026-05-13.json` and add a `eval/README.md` note that says "regenerate with `python scripts/eval_retrieval.py --json eval/baseline_<date>.json` after retrieval changes".

```bash
mkdir -p eval
mv eval_baseline.json eval/baseline_2026-05-13.json
```

Create `eval/README.md`:

```markdown
# Retrieval Evaluation Baselines

Run before/after retrieval changes:

    python scripts/eval_retrieval.py --json eval/baseline_<YYYY-MM-DD>.json

Compare with the prior baseline. Hybrid R@5 should not regress on existing
queries; if it does, investigate the retrieval change before merging.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_retrieval.py eval/baseline_2026-05-13.json eval/README.md
git commit -m "feat(eval): retrieval evaluation harness with R@k/MRR baseline"
```

---

# Group E — P1.1: messages.routing JSONB Audit Field

### Task E.1: Alembic migration to add the column

**Files:**
- Create: `src/db/migrations/versions/0006_messages_routing.py`

- [ ] **Step 1: Verify the current migration head**

Run: `alembic current` (or inspect file order in `src/db/migrations/versions/`)
Expected: `0005_user_auth`. If different, adjust `down_revision` below to match.

- [ ] **Step 2: Create the migration**

Create `src/db/migrations/versions/0006_messages_routing.py`:

```python
"""add messages.routing JSONB column

Stores per-assistant-turn decision context: which template fired, how
many tool iterations ran, whether the premature-NO_MATCH guard fired,
which tools were invoked, etc. Read-only audit data; never used to
re-route a subsequent turn.

Revision ID: 0006_messages_routing
Revises: 0005_user_auth
Create Date: 2026-05-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006_messages_routing"
down_revision: Union[str, None] = "0005_user_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("routing", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "routing")
```

- [ ] **Step 3: Run the migration locally**

```bash
alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade 0005_user_auth -> 0006_messages_routing`.

- [ ] **Step 4: Verify the column exists**

```bash
psql $DATABASE_URL -c "\d messages" | grep routing
```

Expected: `routing | jsonb | | |`.

- [ ] **Step 5: Commit**

```bash
git add src/db/migrations/versions/0006_messages_routing.py
git commit -m "feat(db): migration 0006 — add messages.routing JSONB audit column"
```

---

### Task E.2: Mirror the column in the SQLAlchemy model

**Files:**
- Modify: `src/models/schemas.py` (the `Message` class, lines 52-61)

- [ ] **Step 1: Write a failing test**

Append to `tests/unit/test_models_schemas.py` (or create it):

```python
def test_message_model_has_routing_jsonb_field():
    from src.models.schemas import Message
    col = Message.__table__.c["routing"]
    assert col.nullable is True
    # JSONB is represented as sqlalchemy.dialects.postgresql.JSONB at the type level
    assert "JSONB" in str(col.type).upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models_schemas.py::test_message_model_has_routing_jsonb_field -v`
Expected: FAIL — `routing` attribute does not exist on `Message`.

- [ ] **Step 3: Add the field to `Message`**

In `src/models/schemas.py`, locate the `Message` class (around line 52). After the `citations` line:

```python
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

Add:

```python
    routing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models_schemas.py::test_message_model_has_routing_jsonb_field -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/schemas.py tests/unit/test_models_schemas.py
git commit -m "feat(models): add Message.routing field mirroring migration 0006"
```

---

### Task E.3: Persist routing payload in conversation_engine

**Files:**
- Modify: `src/core/memory_service.py` — `save_assistant_message` signature (location varies; find via grep)
- Modify: `src/core/conversation_engine.py` — build & pass the routing dict at line ~259

- [ ] **Step 1: Find `save_assistant_message`**

Run: `grep -n "def save_assistant_message" src/core/memory_service.py`
Read the function. Note its current signature, which likely accepts `citations=...`. The pattern for `routing` will mirror it.

- [ ] **Step 2: Write a failing test for the engine→memory plumbing**

Create or extend `tests/unit/test_conversation_engine.py` (if no such file exists yet, create it minimally; this is one new test, not a full engine spec). Recipe:

```python
"""Routing plumbing test for ConversationEngine."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.core.conversation_engine import ConversationEngine


class _RecordingMem:
    def __init__(self):
        self.saved_routing = None
        self.documents = []

    async def save_user_message(self, *a, **k): pass
    async def count_documents_by_status(self, sid): return {"ready": 0}
    async def list_messages(self, sid): return []
    async def list_documents(self, sid): return []

    async def save_assistant_message(self, sid, text, *, citations, routing=None):
        self.saved_routing = routing


class _StubLLM:
    async def chat_stream(self, messages, tools=None):
        class _Chunk:
            text_delta = "hi"
            tool_call_deltas = None
            finish_reason = "stop"
        yield _Chunk()


@pytest.mark.asyncio
async def test_engine_records_routing_on_b_empty_path():
    mem = _RecordingMem()
    engine = ConversationEngine(
        mem=mem, llm=_StubLLM(), tools=MagicMock(),
        persona="P", max_tool_iterations=3,
    )
    async for _ in engine.handle_stream(session_id="s", message="hello"):
        pass
    assert mem.saved_routing is not None
    assert mem.saved_routing["template"] == "B-EMPTY"
    assert mem.saved_routing["tool_call_count"] == 0
    assert mem.saved_routing["had_any_tool_call"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_conversation_engine.py -v`
Expected: FAIL — engine does not pass `routing` to `save_assistant_message`.

- [ ] **Step 4: Update `save_assistant_message` signature**

In `src/core/memory_service.py`, find the function and add a `routing: dict | None = None` parameter. Wire it into the `Message(...)` constructor call inside the function. Example:

```python
async def save_assistant_message(
    self, session_id: UUID, text: str, *,
    citations: list | None = None,
    routing: dict | None = None,
) -> Message:
    msg = Message(
        session_id=session_id,
        role=MessageRole.assistant,
        content=text,
        citations=citations,
        routing=routing,
    )
    self.db.add(msg)
    await self.db.commit()
    return msg
```

(Adapt to the actual current body — keep all existing behavior.)

- [ ] **Step 5: Build the routing dict in conversation_engine**

In `src/core/conversation_engine.py`, modify `handle_stream`. The routing payload should be assembled just before each call to `save_assistant_message`. Two call sites exist:

**Site 1 (B-FAILED path, line ~50):**

```python
# before
await self.mem.save_assistant_message(session_id, fixed, citations=[])
# after
await self.mem.save_assistant_message(
    session_id, fixed, citations=[],
    routing={"template": template, "tool_call_count": 0,
             "had_any_tool_call": False, "fixed_response": True},
)
```

**Site 2 (final save at line ~259):**

Right before the existing `await self.mem.save_assistant_message(...)` near line 259, build the routing dict:

```python
routing = {
    "template": template,
    "tool_call_count": tool_call_count,
    "had_any_tool_call": had_any_tool_call,
    "all_found_false": all_found_false,
    "loop_finished_with_stop": loop_finished_with_stop,
    "nudged_for_premature_no_match": nudged_for_premature_no_match,
    "elapsed_seconds": round(_t.monotonic() - _t0, 3),
}
await self.mem.save_assistant_message(
    session_id, final_text_buf,
    citations=unique_citations,
    routing=routing,
)
```

- [ ] **Step 6: Run the engine test + full unit suite**

Run: `pytest tests/unit -v`
Expected: all pass, including the new engine test.

- [ ] **Step 7: Smoke-test against a real conversation**

Start the dev server, send one message via the chat UI (or `curl /chat/stream`). Then query the DB:

```bash
psql $DATABASE_URL -c "SELECT id, role, routing FROM messages ORDER BY id DESC LIMIT 3;"
```

Expected: the latest assistant message row has a non-null `routing` JSON object with the keys above. Tool messages and user messages should have `routing` NULL.

- [ ] **Step 8: Commit**

```bash
git add src/core/memory_service.py src/core/conversation_engine.py tests/unit/test_conversation_engine.py
git commit -m "feat(audit): persist routing decision payload to messages.routing"
```

---

# Group F — P1.2: Recall Tool Protocol Design Note

The doc lists "recall_contact vs recall_follow_up protocol" as **思路借鉴,无工作量** — borrow the design pattern, not the code. doc-qa has nothing equivalent today (only `search_documents`). Capture the pattern so future tool authors apply it correctly.

### Task F.1: Write the design note

**Files:**
- Create: `docs/design/recall-tool-protocol.md`

- [ ] **Step 1: Write the note**

Create `docs/design/recall-tool-protocol.md`:

```markdown
# Recall-Tool Protocol: Fixed Lookup vs. Disambiguation

**Status:** Design pattern reference (no current tool implements both halves; document up-front so V2 tools follow it).

When adding a tool that looks up an entity (a customer, a policy, a
prior case) by user-supplied description, choose one of two response
protocols up front — they have different LLM consumption semantics
and mixing them silently in one tool causes confusing UX.

## Protocol A — Fixed Lookup

The tool returns **at most one match** (or empty). Use when the
caller's intent unambiguously names a single entity.

### Response shape

    {
      "ok": true,
      "match": null | { "id": ..., "name": ..., ... }
    }

### When to use

- "Pull up case 12345" — id is unique.
- "Show me Zhang's policy" — when the user has already disambiguated
  in a prior turn and the tool now has the resolved id.
- "Get the latest annual report" — singleton by definition.

## Protocol B — Disambiguation (candidate list)

The tool returns **N candidates** when the description matches
multiple entities. The LLM is responsible for asking the user to pick
one, then re-invoking the tool with the resolved id in the next turn.

### Response shape

    {
      "ok": true,
      "candidates": [
        { "id": ..., "name": ..., "summary": "...one-line hint..." },
        ...
      ],
      "disambiguation_needed": true
    }

When the description matches exactly one entity, the tool may
collapse to `"candidates": [the_one]` with `"disambiguation_needed":
false` — the LLM-side prompt handles both branches identically.

### When to use

- "That case from last week about the property dispute" — fuzzy.
- "The customer who works in fintech" — likely matches several.
- "Find me a similar past audit decision" — by definition multi-match.

## Why not one polymorphic tool

Mixing A and B in one tool forces the LLM to inspect the response
shape every turn. Empirically that doubles the rate of one-turn-too-
late confirmations ("oh actually I meant the other one"). Splitting
makes each tool's contract one-line in the LLM tool description, and
the LLM uses the right one based on the user's phrasing.

## doc-qa today

`search_documents` is a **chunk-recall tool**, not an entity-recall
tool — it returns the top-K most-relevant chunks regardless of
ambiguity, and downstream rerank + LLM prose synthesis handles the
"which chunk matters" decision. It is **not** an instance of either
protocol; it is the document-level cousin.

When V2 adds entity-level tools (e.g. `recall_similar_case`,
`recall_policy_clause`), pick A or B per the above and document
which in the tool's `description` field.
```

- [ ] **Step 2: Commit**

```bash
git add docs/design/recall-tool-protocol.md
git commit -m "docs(design): recall-tool fixed-lookup vs disambiguation protocol"
```

---

## Self-Review

**Spec coverage check (against `docs/borrow-from-chat-checklist.md`):**

| Spec item | Covered by |
|---|---|
| P0.1 RRF dedup | Task A.1 (`test_rrf_dedups_within_stage`) |
| P0.1 RRF explicit tiebreak | Task A.2 (`test_hybrid_uses_helper_and_tiebreaks_by_chunk_id`) |
| P0.1 RRF N-stage generalization | Task A.1 (`test_rrf_three_stages_generalization`) |
| P0.2 multi-tool DI | Task B.1 (`test_default_factory_wires_search_documents`) |
| P0.2 protocol/business/system error layers | Task B.1 (`test_execute_unknown_tool_*`, `test_execute_tool_exception_*`) + Task B.2 |
| P0.3 Persona double-file | **Already present in repo.** Confirmed in State-of-the-World table. |
| P0.3 Prompt tool-rules section | Task C.1 |
| P0.4 retrieval eval (modes matrix) | Task D.2 — covers `vector × trigram × hybrid`. **Surface dimension (direct vs tool) deferred to V2** — noted in script docstring. |
| P0.4 baseline JSON output | Task D.2 (`--json` flag) + Task D.4 (commit baseline) |
| P1.1 messages.routing JSONB | Tasks E.1, E.2, E.3 |
| P1.2 recall tool protocol | Task F.1 |
| P2.1 / P2.2 (summarizer / router) | **Out of scope** per the checklist itself ("V1 不做"). |

**Placeholder scan:** no TBDs. Every step ships executable code or a runnable command. Two unavoidable items the implementer must adapt:
- `scripts/eval_retrieval.py` references `async_sessionmaker_` and `BgeEmbedder` as placeholder import names — Task D.2 Step 1 calls this out and tells the implementer how to discover the actual names. This is acceptable because the actual names depend on existing project wiring the planner cannot fully audit without spending Task D's full budget.
- Task B.1 Step 1 (grep for `ToolRegistry(`) requires reading the result before doing Step 5. Acceptable because the wiring sites are tiny and the action ("rename to `.default(...)`") is mechanical.

**Type consistency:**
- `_rrf_fuse_scores` returns `dict[str, float]`, callers consume `.items()` / `sorted(...)` — consistent across Tasks A.1 and A.2.
- `ToolRegistry.__init__(tools: dict[str, ToolEntry])` and `ToolRegistry.default(...)` agree — both produce the same internal `_tools` shape.
- `routing` is `dict | None` in both the model (Task E.2) and the engine payload (Task E.3).

---

## Execution Notes

**Order of work:** A → B → C → D → E → F is the recommended order.
- A unlocks the dedup/tiebreak guarantees the eval harness in D depends on for stable comparison.
- B is independent of A but feeds the same overall infra coherence.
- C is purely template-internal, no dependencies.
- D depends on A landing (eval would otherwise compare against a moving target).
- E depends on B conceptually (richer routing data once multi-tool support exists) but does not depend on it in code — could land in parallel.
- F is doc-only and can land anytime.

**Independence within a task:** each task's failing test → implement → passing test → commit cycle is self-contained. A subagent can be dispatched per task without sharing state.

**Total tasks:** 11. Estimate: ~3 working days end-to-end, matching the checklist's P0+P1 estimate of "3-4 天".
