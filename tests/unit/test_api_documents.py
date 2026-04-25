import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set required env vars before importing main
os.environ.setdefault("MOONSHOT_API_KEY", "dummy")
os.environ.setdefault("APP_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/docqa")

from src.main import make_app_default, _production_deps

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_zh.pdf"


@pytest.fixture(autouse=True)
def reset_lru_caches():
    """Each test gets a fresh production-deps / engine bound to its own event loop."""
    import src.db.session as _ses
    _production_deps.cache_clear()
    _ses._default_sm = None
    yield
    _production_deps.cache_clear()
    _ses._default_sm = None


@pytest_asyncio.fixture
async def client(db_session):
    """db_session fixture truncates tables before yielding the client."""
    app = make_app_default()
    transport = ASGITransport(app=app)
    # Patch _run_ingestion to a no-op so background tasks don't load the real
    # BGE model or keep the event loop alive in tests.
    with patch("src.api.documents._run_ingestion", new=AsyncMock(return_value=None)):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def session_id(client):
    r = await client.post("/sessions")
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


@pytest.mark.asyncio
async def test_upload_happy(client, session_id):
    files = {"file": ("sample.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "processing"
    assert body["page_count"] == 3
    assert "document_id" in body


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf_extension(client, session_id):
    files = {"file": ("foo.txt", b"hi", "text/plain")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert ".pdf" in detail or "PDF" in detail


@pytest.mark.asyncio
async def test_upload_rejects_oversize(client, session_id):
    big = b"%PDF-1.4\n" + (b"x" * (21 * 1024 * 1024))
    files = {"file": ("big.pdf", big, "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    assert "20" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_upload_rejects_corrupt_pdf(client, session_id):
    files = {"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    r = await client.post(f"/sessions/{session_id}/documents", files=files)
    assert r.status_code == 400
    assert "无法打开" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_upload_rejects_unknown_session(client):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    r = await client.post(
        "/sessions/00000000-0000-0000-0000-000000000099/documents",
        files=files,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_upload_failure_cleans_temp(client, session_id):
    """Force validation to fail; assert no leftover in .tmp."""
    files = {"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    await client.post(f"/sessions/{session_id}/documents", files=files)

    tmp_dir = Path("data/uploads/.tmp")
    leftovers = list(tmp_dir.glob("*.pdf")) if tmp_dir.exists() else []
    assert leftovers == [], f"leftover temp files: {leftovers}"


@pytest.mark.asyncio
async def test_list_documents(client, session_id):
    files = {"file": ("a.pdf", FIXTURE.read_bytes(), "application/pdf")}
    await client.post(f"/sessions/{session_id}/documents", files=files)
    r = await client.get(f"/sessions/{session_id}/documents")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert "filename" in rows[0] and "status" in rows[0] and "page_count" in rows[0]
