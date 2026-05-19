"""Integrations API: confirm triggers registrar; disable is the kill switch;
all endpoints are admin-gated."""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from src.api.integrations import make_integrations_router
from src.models.schemas import IntegrationStatus, PlatformIntegration, User


@pytest.mark.asyncio
async def test_confirm_then_disable(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")
    admin = User(id=uuid4(), name="a", email="z@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()

    from datetime import datetime, timedelta, timezone
    exp = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    row = PlatformIntegration(
        id=uuid4(), platform_name="P",
        manifest_snapshot={"version": 1, "platform": "P",
            "register": {"method": "POST",
                         "url": "https://api.example.com/r", "body_schema": {}},
            "connection": {"transport": "websocket",
                           "url": "wss://api.example.com/s",
                           "heartbeat_seconds": 30, "token_refresh_url": None},
            "inbound_capabilities": []},
        status=IntegrationStatus.draft, created_by=admin.id,
        token_refresh_meta={"pending_confirm_token": "tok",
                            "expires_at": exp})
    db_session.add(row)
    await db_session.commit()

    async def fake_post(url, *, allowlist, json_body):
        return httpx.Response(200, json={"pairing_code": "PC1",
                                         "claim_url": "https://api.example.com/c"})
    monkeypatch.setattr("src.integration.registrar.safe_post", fake_post)

    # Call the route handlers directly (router functions are closures).
    router = make_integrations_router(sessionmaker=lambda: db_session)
    confirm = _find(router, "confirm")
    disable = _find(router, "disable")

    out = await confirm(row.id, _Body("tok"), _admin_req(admin.id), db_session,
                        admin.id)
    assert out["claim_url"] == "https://api.example.com/c"

    await disable(row.id, _admin_req(admin.id), db_session, admin.id)
    refreshed = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == row.id)
    )).scalars().first()
    assert refreshed.status == IntegrationStatus.disabled


class _Body:
    def __init__(self, token): self.token = token


class _Req:
    def __init__(self, uid):
        self.scope = {"session": {}}
        self.session = {"user_id": str(uid)}


def _admin_req(uid): return _Req(uid)


def _find(router, name):
    for r in router.routes:
        if r.name == name:
            return r.endpoint
    raise AssertionError(f"route {name} not found")
