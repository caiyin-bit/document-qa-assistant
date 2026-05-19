"""Admin-only chat tools for remote-manifest platform onboarding.

fetch_manifest         — SSRF-guarded GET of the .md, extract+validate the
                         agent-integration manifest, persist a draft row.
request_pairing_code   — does NOT register. Returns a confirmation_required
                         signal carrying a short-TTL token bound to the
                         integration id + manifest hash. The actual register
                         call happens only after the user confirms via
                         POST /integrations/{id}/confirm (Task 10).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from src.integration.manifest import ManifestError, extract_manifest
from src.integration.safe_fetch import SafeFetchError, safe_fetch
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)

# Short-lived approval token. Stored in token_refresh_meta until confirm.
_TOKEN_TTL = timedelta(minutes=10)


def _allowlist() -> set[str]:
    raw = os.getenv("INTEGRATION_HOST_ALLOWLIST", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@dataclass
class IntegrationToolDeps:
    # Zero-arg callable whose result is an async context manager yielding
    # an AsyncSession. Convention (whole feature): `async with
    # sessionmaker() as s`. Prod passes an `async_sessionmaker` (calling
    # it returns a session that is itself such a CM, closed on exit);
    # tests pass a factory that yields a shared non-closing session.
    sessionmaker: object


@contextlib.asynccontextmanager
async def _session(deps: IntegrationToolDeps):
    async with deps.sessionmaker() as s:
        yield s


def _manifest_hash(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode()
    ).hexdigest()


class FetchManifestTool:
    SCHEMA = {
        "name": "fetch_manifest",
        "description": (
            "(管理员专用)拉取一个远程 .md,提取并校验其中的 "
            "agent-integration 接入清单,落一条 draft 接入记录。"
            "散文不参与控制流。返回 integration_id 与平台摘要。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "远程 .md 的 https URL"},
            },
            "required": ["url"],
        },
    }

    def __init__(self, deps: IntegrationToolDeps):
        self.deps = deps

    async def execute(self, *, session_id, user_id, url: str) -> dict:
        allow = _allowlist()
        if not allow:
            return {"ok": False, "error": "config",
                    "message": "INTEGRATION_HOST_ALLOWLIST 未配置,拒绝所有拉取"}
        try:
            md = await safe_fetch(url, allowlist=allow)
        except SafeFetchError as e:
            return {"ok": False, "error": "fetch_blocked", "message": str(e)}
        try:
            m = extract_manifest(md, allowlist=allow)
        except ManifestError as e:
            return {"ok": False, "error": "manifest_invalid", "message": str(e)}
        snapshot = m.model_dump()
        row = PlatformIntegration(
            id=uuid4(),
            platform_name=m.platform,
            manifest_snapshot=snapshot,
            status=IntegrationStatus.draft,
            created_by=user_id,
            pairing_secret_ciphertext=None,
            token_refresh_meta=None,
        )
        async with _session(self.deps) as db:
            db.add(row)
            await db.commit()
        log.info("integration.fetch_manifest id=%s platform=%s by=%s",
                 row.id, m.platform, user_id)
        return {
            "ok": True,
            "integration_id": str(row.id),
            "platform": m.platform,
            "register_url": m.register.url,
            "connection_url": m.connection.url,
            "inbound_capabilities": m.inbound_capabilities,
        }


class RequestPairingCodeTool:
    SCHEMA = {
        "name": "request_pairing_code",
        "description": (
            "(管理员专用)对一个 draft 接入记录发起配对码申请。"
            "本工具不直接注册:它返回 confirmation_required,"
            "必须由用户在前端确认后才会真正向外部平台发注册请求。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "integration_id": {"type": "string"},
            },
            "required": ["integration_id"],
        },
    }

    def __init__(self, deps: IntegrationToolDeps):
        self.deps = deps

    async def execute(self, *, session_id, user_id, integration_id: str) -> dict:
        async with _session(self.deps) as db:
            row = (await db.execute(
                select(PlatformIntegration).where(
                    PlatformIntegration.id == UUID(integration_id)
                )
            )).scalars().first()
            if row is None:
                return {"ok": False, "error": "not_found",
                        "message": f"integration {integration_id} 不存在"}
            if row.status != IntegrationStatus.draft:
                return {"ok": False, "error": "bad_state",
                        "message": f"状态须为 draft,当前 {row.status}"}
            token = secrets.token_urlsafe(24)
            row.token_refresh_meta = {
                "pending_confirm_token": token,
                "manifest_hash": _manifest_hash(row.manifest_snapshot),
                "expires_at": (datetime.now(timezone.utc)
                               + _TOKEN_TTL).isoformat(),
                "requested_by": str(user_id),
            }
            await db.commit()
            m = row.manifest_snapshot
        summary = (
            f"平台: {m['platform']}\n"
            f"注册端点: {m['register']['method']} {m['register']['url']}\n"
            f"连接目标: {m['connection']['transport']} {m['connection']['url']}\n"
            f"声明的入站能力: {', '.join(m.get('inbound_capabilities') or []) or '(无)'}"
        )
        return {
            "ok": True,
            "status": "confirmation_required",
            "integration_id": integration_id,
            "token": token,
            "summary": summary,
        }


def build_integration_tools(deps: IntegrationToolDeps):
    """Return [(name, schema, tool), ...] for registry wiring."""
    ft = FetchManifestTool(deps)
    rt = RequestPairingCodeTool(deps)
    return [
        ("fetch_manifest", FetchManifestTool.SCHEMA, ft),
        ("request_pairing_code", RequestPairingCodeTool.SCHEMA, rt),
    ]
