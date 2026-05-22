"""refresh_if_due: skips when no expiry, rotates secret on success,
flips to degraded on any failure."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from src.connector.token_refresh import refresh_if_due
from src.integration.crypto import decrypt_secret, encrypt_secret
from src.models.schemas import IntegrationStatus, PlatformIntegration, User


async def _row(db, *, meta, code="OLD"):
    admin = User(id=uuid4(), name="a", email=f"{uuid4()}@x.com", is_admin=True)
    db.add(admin)
    await db.commit()
    r = PlatformIntegration(
        id=uuid4(), platform_name="P", manifest_snapshot={},
        status=IntegrationStatus.active, created_by=admin.id,
        pairing_secret_ciphertext=encrypt_secret(code),
        token_refresh_meta=meta)
    db.add(r)
    await db.commit()
    return r


@pytest.mark.asyncio
async def test_skips_when_no_expiry(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    r = await _row(db_session, meta={"registered_at": "x"})
    assert await refresh_if_due(db_session, r) == "skipped"


@pytest.mark.asyncio
async def test_skips_when_not_yet_due(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    far = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = await _row(db_session, meta={"token_refresh_url":
                   "https://api.example.com/t", "token_expires_at": far})
    assert await refresh_if_due(db_session, r) == "skipped"


@pytest.mark.asyncio
async def test_refreshes_and_rotates_secret(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")
    soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    r = await _row(db_session, meta={"token_refresh_url":
                   "https://api.example.com/t", "token_expires_at": soon})

    async def fake_post(url, *, allowlist, json_body):
        assert json_body == {"pairing_code": "OLD"}
        return httpx.Response(200, json={"pairing_code": "NEW",
                                         "expires_in": 3600})
    monkeypatch.setattr("src.connector.token_refresh.safe_post", fake_post)
    assert await refresh_if_due(db_session, r) == "refreshed"
    assert decrypt_secret(r.pairing_secret_ciphertext) == "NEW"
    assert r.status == IntegrationStatus.active


@pytest.mark.asyncio
async def test_failure_sets_degraded(db_session, monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "s")
    monkeypatch.setenv("INTEGRATION_HOST_ALLOWLIST", "api.example.com")
    soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    r = await _row(db_session, meta={"token_refresh_url":
                   "https://api.example.com/t", "token_expires_at": soon})

    async def fake_post(url, *, allowlist, json_body):
        return httpx.Response(503, text="down")
    monkeypatch.setattr("src.connector.token_refresh.safe_post", fake_post)
    assert await refresh_if_due(db_session, r) == "degraded"
    assert r.status == IntegrationStatus.degraded
