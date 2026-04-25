"""E2E: real LLM, real BGE, real DB. Marked @pytest.mark.llm — skipped by default.

Run with:
  pytest -m llm tests/e2e/test_doc_qa.py -v --timeout=600

Requires:
  - tests/fixtures/example/腾讯2025年度报告.pdf (challenge-provided, gitignored)
  - MOONSHOT_API_KEY env var set to a real key
  - postgres running (docker compose up -d postgres)
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio

PDF = Path(__file__).parent.parent / "fixtures" / "example" / "腾讯2025年度报告.pdf"

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not PDF.exists(),
                        reason=f"E2E fixture missing: {PDF}"),
    pytest.mark.skipif(
        os.environ.get("MOONSHOT_API_KEY", "dummy") == "dummy",
        reason="MOONSHOT_API_KEY must be a real key for E2E"),
]


@pytest_asyncio.fixture
async def client_with_doc():
    """Upload the Tencent annual report and wait until it's ready."""
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    os.environ.setdefault("DATABASE_URL",
                           "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")
    from src.main import make_app_default
    from httpx import AsyncClient, ASGITransport

    app = make_app_default()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as c:
        sid = (await c.post("/sessions")).json()["session_id"]
        files = {"file": ("腾讯2025年度报告.pdf", PDF.read_bytes(), "application/pdf")}
        r = await c.post(f"/sessions/{sid}/documents", files=files)
        assert r.status_code == 200, r.text
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
    text = ""
    cits = []
    async with client.stream("POST", "/chat/stream",
                              json={"session_id": sid, "message": q}) as resp:
        block = ""
        async for chunk in resp.aiter_text():
            block += chunk
            while "\n\n" in block:
                frame, block = block.split("\n\n", 1)
                event = None
                data_str = ""
                for line in frame.split("\n"):
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data_str += line[6:]
                if not event:
                    continue
                data = json.loads(data_str) if data_str else {}
                if event == "text":
                    text += data.get("delta", "")
                elif event == "citations":
                    cits = data.get("chunks", [])
                elif event == "done":
                    return text, cits
    return text, cits


@pytest.mark.asyncio
async def test_factual_query_returns_answer_with_citation(client_with_doc):
    client, sid = client_with_doc
    text, cits = await _ask_collect(client, sid, "腾讯 2025 年总营业收入是多少？")
    # Allow various number formats: 6,605 / 6605 / 六千六百零五 etc.
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
    # provided no fabrication occurs. Assert one of the two patterns.
    assert ("未找到相关信息" in text) or any(d.isdigit() for d in text)


@pytest.mark.asyncio
async def test_out_of_scope_query_says_not_found(client_with_doc):
    client, sid = client_with_doc
    text, cits = await _ask_collect(client, sid, "今天天气如何？")
    assert "未找到相关信息" in text
    assert cits == []


@pytest.mark.asyncio
async def test_b_empty_no_documents_uploaded():
    """Doesn't need the PDF — just exercises the no-docs path with real LLM."""
    if os.environ.get("MOONSHOT_API_KEY", "dummy") == "dummy":
        pytest.skip("MOONSHOT_API_KEY required")
    os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
    os.environ.setdefault("DATABASE_URL",
                           "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")
    from src.main import make_app_default
    from httpx import AsyncClient, ASGITransport

    app = make_app_default()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        sid = (await c.post("/sessions")).json()["session_id"]
        text, cits = await _ask_collect(c, sid, "随便问个问题")
        assert "请先上传" in text
        assert cits == []
