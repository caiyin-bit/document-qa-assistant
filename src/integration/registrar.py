"""Confirmed registration: the ONLY place that makes the side-effecting
register call. Reached only after HITL confirm (Task 10 endpoint)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from src.integration.crypto import encrypt_secret
from src.integration.safe_fetch import SafeFetchError, safe_post
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)


class RegistrarError(Exception):
    pass


def _allowlist() -> set[str]:
    raw = os.getenv("INTEGRATION_HOST_ALLOWLIST", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


async def confirm_and_register(db, *, integration_id: UUID, token: str) -> dict:
    row = (await db.execute(
        select(PlatformIntegration).where(
            PlatformIntegration.id == integration_id)
    )).scalars().first()
    if row is None:
        raise RegistrarError("integration not found")
    if row.status != IntegrationStatus.draft:
        raise RegistrarError(f"bad state: {row.status}")
    meta = row.token_refresh_meta or {}
    if not meta.get("pending_confirm_token") or \
            meta["pending_confirm_token"] != token:
        raise RegistrarError("invalid confirm token")
    try:
        expires = datetime.fromisoformat(meta["expires_at"])
    except (KeyError, ValueError) as e:
        raise RegistrarError("malformed token meta") from e
    if datetime.now(timezone.utc) >= expires:
        raise RegistrarError("confirm token expired")

    snap = row.manifest_snapshot
    reg = snap["register"]
    try:
        resp = await safe_post(
            reg["url"], allowlist=_allowlist(),
            json_body={"platform": snap["platform"]},
        )
    except SafeFetchError as e:
        raise RegistrarError(f"register fetch blocked: {e}") from e
    if resp.status_code // 100 != 2:
        # Keep draft so the admin can retry; do not leave a half-state.
        raise RegistrarError(
            f"register returned {resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise RegistrarError("register response not JSON") from e
    pairing_code = body.get("pairing_code")
    claim_url = body.get("claim_url")
    if not pairing_code:
        raise RegistrarError("register response missing pairing_code")

    row.pairing_secret_ciphertext = encrypt_secret(pairing_code)
    row.status = IntegrationStatus.active
    meta = {"registered_at": datetime.now(timezone.utc).isoformat()}
    expires_in = body.get("expires_in")
    refresh_url = snap["connection"].get("token_refresh_url")
    if refresh_url and expires_in:
        meta["token_refresh_url"] = refresh_url
        meta["token_expires_at"] = (
            datetime.now(timezone.utc)
            + timedelta(seconds=int(expires_in))
        ).isoformat()
    row.token_refresh_meta = meta
    await db.commit()
    log.info("integration.registered id=%s platform=%s",
             row.id, snap["platform"])
    return {"integration_id": str(row.id), "claim_url": claim_url,
            "status": "active"}
