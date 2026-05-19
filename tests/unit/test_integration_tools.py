"""fetch_manifest stores a draft; request_pairing_code returns a
confirmation_required signal (never registers directly)."""
from __future__ import annotations

import contextlib
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.tools.integration_tools import IntegrationToolDeps, build_integration_tools


@contextlib.asynccontextmanager
async def _sm(session):
    """Test sessionmaker: yield the shared fixture session, never close it."""
    yield session

_MD = """
```agent-integration
version: 1
platform: ExamplePlatform
register:
  method: POST
  url: https://api.example.com/agents/register
  body_schema: {}
connection:
  transport: websocket
  url: wss://api.example.com/agent/stream
  heartbeat_seconds: 30
  token_refresh_url: https://api.example.com/agents/token
inbound_capabilities: [ping]
```
"""


def _tools(db, monkeypatch):
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")

    async def fake_fetch(url, *, allowlist):
        assert "api.example.com" in allowlist
        return _MD

    monkeypatch.setattr("src.tools.integration_tools.safe_fetch", fake_fetch)
    deps = IntegrationToolDeps(sessionmaker=lambda: _sm(db))
    return {n: t for n, _, t in build_integration_tools(deps)}


@pytest.mark.asyncio
async def test_fetch_manifest_stores_draft(db_session, monkeypatch):
    from src.models.schemas import IntegrationStatus, PlatformIntegration, User
    admin = User(id=uuid4(), name="a", email="a@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()

    tools = _tools(db_session, monkeypatch)
    res = await tools["fetch_manifest"].execute(
        session_id=uuid4(), user_id=admin.id,
        url="https://api.example.com/SKILL.md",
    )
    assert res["ok"] is True
    assert res["platform"] == "ExamplePlatform"
    iid = res["integration_id"]
    row = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == iid)
    )).scalars().first()
    assert row.status == IntegrationStatus.draft


@pytest.mark.asyncio
async def test_request_pairing_code_returns_confirmation(db_session, monkeypatch):
    from src.models.schemas import User
    admin = User(id=uuid4(), name="a", email="b@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()
    tools = _tools(db_session, monkeypatch)
    fetched = await tools["fetch_manifest"].execute(
        session_id=uuid4(), user_id=admin.id,
        url="https://api.example.com/SKILL.md",
    )
    res = await tools["request_pairing_code"].execute(
        session_id=uuid4(), user_id=admin.id,
        integration_id=fetched["integration_id"],
    )
    assert res["ok"] is True
    assert res["status"] == "confirmation_required"
    assert res["integration_id"] == fetched["integration_id"]
    assert res["token"]
    assert "ExamplePlatform" in res["summary"]
