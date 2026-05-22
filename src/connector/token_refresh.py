"""Connector token refresh — spec error-table parity.

refresh_if_due(db, row): no-op unless token_refresh_meta carries both
token_refresh_url and a token_expires_at within the skew window. On any
failure the row is flipped to `degraded` (and logged as the spec's
"告警"); the supervisor then drops its connection on the next poll.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from src.integration.crypto import decrypt_secret, encrypt_secret
from src.integration.safe_fetch import safe_post
from src.models.schemas import IntegrationStatus

log = logging.getLogger(__name__)


def _allowlist() -> set[str]:
    raw = os.getenv("INTEGRATION_HOST_ALLOWLIST", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


async def _degrade(db, row, why: str) -> str:
    row.status = IntegrationStatus.degraded
    await db.commit()
    log.warning("token refresh failed id=%s -> degraded: %s", row.id, why)
    return "degraded"


async def refresh_if_due(db, row, *, skew_seconds: int = 60) -> str:
    meta = row.token_refresh_meta or {}
    url = meta.get("token_refresh_url")
    exp_raw = meta.get("token_expires_at")
    if not url or not exp_raw:
        return "skipped"
    try:
        expires = datetime.fromisoformat(exp_raw)
    except ValueError:
        return "skipped"
    if datetime.now(timezone.utc) < expires - timedelta(seconds=skew_seconds):
        return "skipped"
    try:
        current = decrypt_secret(row.pairing_secret_ciphertext)
        resp = await safe_post(url, allowlist=_allowlist(),
                               json_body={"pairing_code": current})
    except Exception as e:  # noqa: BLE001 — any failure → degraded, never crash
        return await _degrade(db, row, repr(e))
    if resp.status_code // 100 != 2:
        return await _degrade(db, row, f"status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        return await _degrade(db, row, "response not JSON")
    new_code = body.get("pairing_code")
    if not new_code:
        return await _degrade(db, row, "missing pairing_code")
    row.pairing_secret_ciphertext = encrypt_secret(new_code)
    new_meta = dict(meta)
    expires_in = body.get("expires_in")
    if expires_in:
        new_meta["token_expires_at"] = (
            datetime.now(timezone.utc)
            + timedelta(seconds=int(expires_in))
        ).isoformat()
    row.token_refresh_meta = new_meta
    await db.commit()
    log.info("token refreshed id=%s", row.id)
    return "refreshed"
