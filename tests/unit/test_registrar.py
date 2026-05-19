"""Registrar: validates confirm token, POSTs register endpoint, persists
encrypted pairing secret, flips status to active. Mocks safe_post."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from src.integration.crypto import decrypt_secret
from src.integration.registrar import RegistrarError, confirm_and_register
from src.models.schemas import IntegrationStatus, PlatformIntegration, User

_SNAP = {
    "version": 1, "platform": "ExamplePlatform",
    "register": {"method": "POST",
                 "url": "https://api.example.com/agents/register",
                 "body_schema": {}},
    "connection": {"transport": "websocket",
                   "url": "wss://api.example.com/agent/stream",
                   "heartbeat_seconds": 30,
                   "token_refresh_url": "https://api.example.com/agents/token"},
    "inbound_capabilities": ["ping"],
}


async def _seed(db, token="tok", expired=False):
    admin = User(id=uuid4(), name="a", email=f"{uuid4()}@x.com", is_admin=True)
    db.add(admin)
    await db.commit()
    exp = datetime.now(timezone.utc) + (timedelta(minutes=-1) if expired
                                        else timedelta(minutes=5))
    row = PlatformIntegration(
        id=uuid4(), platform_name="ExamplePlatform",
        manifest_snapshot=_SNAP, status=IntegrationStatus.draft,
        created_by=admin.id, pairing_secret_ciphertext=None,
        token_refresh_meta={"pending_confirm_token": token,
                            "expires_at": exp.isoformat()},
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_confirm_and_register_happy_path(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")
    row = await _seed(db_session)

    async def fake_post(url, *, allowlist, json_body):
        return httpx.Response(
            200, json={"pairing_code": "PC-999",
                       "claim_url": "https://api.example.com/claim/xyz"})

    monkeypatch.setattr("src.integration.registrar.safe_post", fake_post)
    out = await confirm_and_register(
        db_session, integration_id=row.id, token="tok")
    assert out["claim_url"] == "https://api.example.com/claim/xyz"
    refreshed = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == row.id)
    )).scalars().first()
    assert refreshed.status == IntegrationStatus.active
    assert decrypt_secret(refreshed.pairing_secret_ciphertext) == "PC-999"


@pytest.mark.asyncio
async def test_bad_token_rejected(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    row = await _seed(db_session, token="real")
    with pytest.raises(RegistrarError):
        await confirm_and_register(db_session, integration_id=row.id,
                                   token="wrong")


@pytest.mark.asyncio
async def test_expired_token_rejected(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    row = await _seed(db_session, token="tok", expired=True)
    with pytest.raises(RegistrarError):
        await confirm_and_register(db_session, integration_id=row.id,
                                   token="tok")


@pytest.mark.asyncio
async def test_register_non_2xx_keeps_draft(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")
    row = await _seed(db_session)

    async def fake_post(url, *, allowlist, json_body):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr("src.integration.registrar.safe_post", fake_post)
    with pytest.raises(RegistrarError):
        await confirm_and_register(db_session, integration_id=row.id,
                                   token="tok")
    refreshed = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == row.id)
    )).scalars().first()
    assert refreshed.status == IntegrationStatus.draft
