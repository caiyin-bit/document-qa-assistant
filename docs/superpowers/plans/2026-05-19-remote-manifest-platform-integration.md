# Remote-Manifest Platform Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让面向用户的聊天 agent 通过读取远程 `.md` 内嵌的结构化清单,经管理员触发 + HITL 确认自主申请配对码,并由独立守护进程与外部平台维持双向持久连接。

**Architecture:** 聊天 loop 加两个 admin-only 工具(`fetch_manifest` / `request_pairing_code`);`request_pairing_code` 不直接注册,而是返回 `confirmation_required` 信号,引擎发同名 SSE 事件并结束本轮;用户在前端确认后调独立 `POST /integrations/{id}/confirm` 端点,由 registrar 真正发注册请求并把凭证加密落库;独立 asyncio 守护进程 `src.connector.main` 读 active 行维持持久连接(心跳/重连/token 刷新/受控入站)。

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + Postgres;httpx(safe_fetch);cryptography Fernet(凭证加密,新增依赖);websockets(连接守护,新增依赖);pytest + pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-05-19-remote-manifest-platform-integration-design.md`

**Spec 实现级细化(经计划阶段确认):** HITL 不做"暂停/续发 LLM 回合"的引擎深改;改为工具返回 `confirmation_required` + 引擎发事件结束本轮 + 独立 confirm 端点触发注册。spec"副作用前必须人工确认"的本质保留。

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/db/migrations/versions/0007_user_is_admin.py` | Create | `users.is_admin` 列 |
| `src/db/migrations/versions/0008_platform_integration.py` | Create | `platform_integration` 表 |
| `src/models/schemas.py` | Modify | `User.is_admin` + `PlatformIntegration` 模型 + `IntegrationStatus` enum |
| `src/api/auth.py` | Modify | `is_current_user_admin` + `require_admin`;`MeResponse.is_admin` |
| `src/integration/__init__.py` | Create | 包标记 |
| `src/integration/safe_fetch.py` | Create | SSRF 防护的 GET/POST |
| `src/integration/manifest.py` | Create | manifest pydantic 模型 + 提取/校验 |
| `src/integration/crypto.py` | Create | Fernet 凭证加解密 |
| `src/integration/registrar.py` | Create | 按 manifest 发注册请求 + 落库 |
| `src/tools/integration_tools.py` | Create | `FetchManifestTool` / `RequestPairingCodeTool` |
| `src/core/tool_registry.py` | Modify | admin-only 工具过滤 + 透传 user 上下文 |
| `src/core/conversation_engine.py` | Modify | 透传 user 上下文;`confirmation_required` 信号处理 |
| `src/api/sse.py` | Modify | `confirmation_required` StreamEvent |
| `src/api/integrations.py` | Create | `GET /integrations` + `POST /integrations/{id}/confirm` + 熔断 `POST /integrations/{id}/disable` |
| `src/api/chat.py` | Modify | 透传 user_id/is_admin 进引擎;注册整合工具 |
| `src/main.py` | Modify | 挂载 integrations 路由 |
| `src/connector/__init__.py` | Create | 包标记 |
| `src/connector/inbound.py` | Create | 入站命令 schema 校验 + 能力白名单 + 固定 handler |
| `src/connector/connection.py` | Create | 单 integration 连接:transport/心跳/重连 |
| `src/connector/token_refresh.py` | Create | token 到期刷新;失败置 degraded |
| `src/connector/main.py` | Create | 守护进程入口:轮询 active 行,管理连接生命周期 |
| `pyproject.toml` | Modify | 新增 `cryptography`、`websockets` 依赖 |
| `config.yaml` | Modify | 无新结构;allowlist/secret 走 env(文档注明) |

测试文件随各 Task 列出。

---

## Phase 0 — Admin role (prerequisite)

### Task 1: User.is_admin column + migration

**Files:**
- Create: `src/db/migrations/versions/0007_user_is_admin.py`
- Modify: `src/models/schemas.py:30-39`
- Test: `tests/unit/test_models_schemas.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models_schemas.py`:

```python
def test_user_has_is_admin_default_false():
    from src.models.schemas import User
    u = User(name="x")
    # SQLAlchemy column default applies at flush; the Python-side default
    # is declared so attribute is None until flush — assert the column exists.
    assert "is_admin" in User.__table__.columns
    assert User.__table__.columns["is_admin"].default.arg is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models_schemas.py::test_user_has_is_admin_default_false -v`
Expected: FAIL — `KeyError: 'is_admin'`

- [ ] **Step 3: Add the column**

In `src/models/schemas.py`, add `Boolean` to the sqlalchemy import line (line 6-9 group) and add to `User`:

```python
from sqlalchemy import (
    BIGINT, Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer,
    String, Text, func,
)
```

In class `User`, after `password_hash` (line 38):

```python
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models_schemas.py::test_user_has_is_admin_default_false -v`
Expected: PASS

- [ ] **Step 5: Write the migration**

Create `src/db/migrations/versions/0007_user_is_admin.py`:

```python
"""users.is_admin — admin role for platform integration onboarding.

Revision ID: 0007_user_is_admin
Revises: 0006_messages_routing
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_user_is_admin"
down_revision = "0006_messages_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
```

- [ ] **Step 6: Apply migration and verify**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/test_db_smoke.py -v`
Expected: migration applies cleanly; db smoke PASS

- [ ] **Step 7: Commit**

```bash
git add src/models/schemas.py src/db/migrations/versions/0007_user_is_admin.py tests/unit/test_models_schemas.py
git commit -m "feat(auth): add users.is_admin column"
```

### Task 2: require_admin dependency + MeResponse.is_admin

**Files:**
- Modify: `src/api/auth.py`
- Test: `tests/unit/test_auth_admin.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_admin.py`:

```python
"""require_admin dependency + is_current_user_admin resolution."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.auth import require_admin


class _Req:
    def __init__(self, scope_session: dict | None):
        self.scope = {"session": {}} if scope_session is not None else {}
        self.session = scope_session if scope_session is not None else {}


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin(db_session):
    from src.models.schemas import User
    from uuid import uuid4
    u = User(id=uuid4(), name="n", email="a@b.com", is_admin=False)
    db_session.add(u)
    await db_session.commit()
    req = _Req({"user_id": str(u.id)})
    with pytest.raises(HTTPException) as ei:
        await require_admin(req, db_session)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_allows_admin(db_session):
    from src.models.schemas import User
    from uuid import uuid4
    u = User(id=uuid4(), name="n", email="c@d.com", is_admin=True)
    db_session.add(u)
    await db_session.commit()
    req = _Req({"user_id": str(u.id)})
    assert await require_admin(req, db_session) == u.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_admin.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_admin'`

- [ ] **Step 3: Implement require_admin**

In `src/api/auth.py`, after `require_user` (line 176), add:

```python
async def require_admin(request: Request, db: AsyncSession) -> UUID:
    """FastAPI dependency: 401 if no user, 403 if user is not admin.

    Admin gates system-level platform integration onboarding (registering
    the whole system into an external platform). A regular tenant user
    must never reach these tools/endpoints.
    """
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(401, "请先登录")
    user = await db.get(User, uid)
    if user is None or not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return uid


async def is_current_user_admin(request: Request, db: AsyncSession) -> bool:
    """Non-raising variant used by the chat tool gate."""
    uid = current_user_id(request)
    if uid is None:
        return False
    user = await db.get(User, uid)
    return bool(user and user.is_admin)
```

- [ ] **Step 4: Add is_admin to MeResponse**

In `MeResponse` (line 55-59) add field:

```python
class MeResponse(BaseModel):
    user_id: UUID
    email: str | None
    name: str
    is_demo: bool
    is_admin: bool = False
```

In the `me` endpoint return (line 149-152), and in `register`/`login` returns (lines 100-102, 125-127), add `is_admin=user.is_admin`. Example for `me`:

```python
        return MeResponse(
            user_id=user.id, email=user.email, name=user.name,
            is_demo=is_demo, is_admin=user.is_admin,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_auth_admin.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/auth.py tests/unit/test_auth_admin.py
git commit -m "feat(auth): require_admin dependency + is_admin in MeResponse"
```

---

## Phase 1 — safe_fetch + manifest contract

### Task 3: safe_fetch (SSRF guard)

**Files:**
- Create: `src/integration/__init__.py`
- Create: `src/integration/safe_fetch.py`
- Test: `tests/unit/test_safe_fetch.py` (create)

- [ ] **Step 1: Create package marker**

Create `src/integration/__init__.py`:

```python
```

(empty file)

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_safe_fetch.py`:

```python
"""safe_fetch SSRF guard: scheme/allowlist/private-IP/redirect rejection."""
from __future__ import annotations

import pytest

from src.integration.safe_fetch import SafeFetchError, _ip_is_blocked, safe_fetch


def test_private_and_metadata_ips_blocked():
    for ip in ["127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254",
               "100.64.0.1", "::1", "fe80::1"]:
        assert _ip_is_blocked(ip) is True


def test_public_ip_not_blocked():
    assert _ip_is_blocked("93.184.216.34") is False


@pytest.mark.asyncio
async def test_rejects_non_https():
    with pytest.raises(SafeFetchError):
        await safe_fetch("http://example.com/x", allowlist={"example.com"})


@pytest.mark.asyncio
async def test_rejects_host_not_in_allowlist():
    with pytest.raises(SafeFetchError):
        await safe_fetch("https://evil.com/x", allowlist={"example.com"})


@pytest.mark.asyncio
async def test_empty_allowlist_denies_all():
    with pytest.raises(SafeFetchError):
        await safe_fetch("https://example.com/x", allowlist=set())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_safe_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: src.integration.safe_fetch`

- [ ] **Step 4: Implement safe_fetch**

Create `src/integration/safe_fetch.py`:

```python
"""SSRF-guarded HTTP for manifest fetch + connector token refresh.

Rules (spec §Security Model):
  - https only
  - host must be in the caller-provided allowlist (exact, case-insensitive)
  - every resolved IP must be public (reject private/loopback/link-local/
    CGNAT/metadata/multicast/reserved)
  - no redirects (a 3xx is rejected, not followed)
  - 10s timeout, 256 KB response cap
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_TIMEOUT_S = 10.0
_MAX_BYTES = 256 * 1024
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class SafeFetchError(Exception):
    pass


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
        return True
    if ip.version == 4 and ip in _CGNAT:
        return True
    return False


def _check_url(url: str, allowlist: set[str]) -> str:
    parts = urlparse(url)
    if parts.scheme != "https":
        raise SafeFetchError(f"scheme must be https: {url}")
    host = (parts.hostname or "").lower()
    if not host or host not in {h.lower() for h in allowlist}:
        raise SafeFetchError(f"host not in allowlist: {host!r}")
    # Resolve and reject if ANY address is blocked (DNS-rebind defence).
    try:
        infos = socket.getaddrinfo(host, parts.port or 443)
    except socket.gaierror as e:
        raise SafeFetchError(f"DNS resolution failed: {host}") from e
    for info in infos:
        if _ip_is_blocked(info[4][0]):
            raise SafeFetchError(f"resolves to blocked IP: {info[4][0]}")
    return host


async def _request(method: str, url: str, allowlist: set[str],
                   json_body: dict | None = None) -> httpx.Response:
    _check_url(url, allowlist)
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=_TIMEOUT_S,
    ) as client:
        resp = await client.request(method, url, json=json_body)
    if resp.is_redirect:
        raise SafeFetchError(f"redirect not allowed: {resp.status_code} {url}")
    if len(resp.content) > _MAX_BYTES:
        raise SafeFetchError("response too large")
    return resp


async def safe_fetch(url: str, *, allowlist: set[str]) -> str:
    """GET; return text. Raises SafeFetchError on any guard failure."""
    resp = await _request("GET", url, allowlist)
    resp.raise_for_status()
    return resp.text


async def safe_post(url: str, *, allowlist: set[str],
                    json_body: dict) -> httpx.Response:
    """POST json; return the raw response (caller inspects status/body)."""
    return await _request("POST", url, allowlist, json_body=json_body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_safe_fetch.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/integration/__init__.py src/integration/safe_fetch.py tests/unit/test_safe_fetch.py
git commit -m "feat(integration): SSRF-guarded safe_fetch/safe_post"
```

### Task 4: Manifest model + extraction/validation

**Files:**
- Create: `src/integration/manifest.py`
- Test: `tests/unit/test_manifest.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_manifest.py`:

```python
"""agent-integration manifest extraction + validation."""
from __future__ import annotations

import pytest

from src.integration.manifest import ManifestError, extract_manifest

_ALLOW = {"api.example.com"}

_GOOD = """
# Some platform onboarding doc (prose ignored for control flow)

```agent-integration
version: 1
platform: ExamplePlatform
register:
  method: POST
  url: https://api.example.com/agents/register
  body_schema: {agent_name: string}
connection:
  transport: websocket
  url: wss://api.example.com/agent/stream
  heartbeat_seconds: 30
  token_refresh_url: https://api.example.com/agents/token
inbound_capabilities:
  - ping
  - request_status
```
trailing prose
"""


def test_extract_good_manifest():
    m = extract_manifest(_GOOD, allowlist=_ALLOW)
    assert m.platform == "ExamplePlatform"
    assert m.register.url == "https://api.example.com/agents/register"
    assert m.connection.transport == "websocket"
    assert m.inbound_capabilities == ["ping", "request_status"]


def test_missing_fenced_block_rejected():
    with pytest.raises(ManifestError):
        extract_manifest("no manifest here", allowlist=_ALLOW)


def test_register_host_not_in_allowlist_rejected():
    bad = _GOOD.replace("api.example.com/agents/register",
                         "evil.com/agents/register")
    with pytest.raises(ManifestError):
        extract_manifest(bad, allowlist=_ALLOW)


def test_non_https_register_rejected():
    bad = _GOOD.replace("https://api.example.com/agents/register",
                         "http://api.example.com/agents/register")
    with pytest.raises(ManifestError):
        extract_manifest(bad, allowlist=_ALLOW)


def test_unknown_transport_rejected():
    bad = _GOOD.replace("transport: websocket", "transport: carrierpigeon")
    with pytest.raises(ManifestError):
        extract_manifest(bad, allowlist=_ALLOW)


def test_unknown_top_level_field_rejected():
    bad = _GOOD.replace("version: 1", "version: 1\nexec_shell: rm -rf /")
    with pytest.raises(ManifestError):
        extract_manifest(bad, allowlist=_ALLOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: src.integration.manifest`

- [ ] **Step 3: Implement manifest**

Create `src/integration/manifest.py`:

```python
"""agent-integration manifest: the ONLY thing in a remote .md that drives
control flow. Prose is never executed (spec, approach A).

Contract: the .md must contain exactly one fenced block tagged
`agent-integration` whose body is YAML matching IntegrationManifest.
Unknown fields are rejected (extra="forbid") so a poisoned .md cannot
smuggle side-effecting directives.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

_FENCE_RE = re.compile(
    r"```agent-integration\s*\n(.*?)\n```", re.DOTALL,
)


class ManifestError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterSpec(_Strict):
    method: Literal["POST"]
    url: str
    body_schema: dict = {}


class ConnectionSpec(_Strict):
    transport: Literal["websocket", "sse", "poll"]
    url: str
    heartbeat_seconds: int = 30
    token_refresh_url: str | None = None


class IntegrationManifest(_Strict):
    version: Literal[1]
    platform: str
    register: RegisterSpec
    connection: ConnectionSpec
    inbound_capabilities: list[str] = []


def _enforce_url(url: str, allowlist: set[str], *, allow_wss: bool) -> None:
    parts = urlparse(url)
    ok_scheme = {"https"} | ({"wss"} if allow_wss else set())
    if parts.scheme not in ok_scheme:
        raise ManifestError(f"insecure/invalid scheme: {url}")
    host = (parts.hostname or "").lower()
    if host not in {h.lower() for h in allowlist}:
        raise ManifestError(f"host not in allowlist: {host!r}")


def extract_manifest(markdown: str, *, allowlist: set[str]) -> IntegrationManifest:
    matches = _FENCE_RE.findall(markdown)
    if len(matches) != 1:
        raise ManifestError(
            f"expected exactly 1 agent-integration block, found {len(matches)}"
        )
    try:
        data = yaml.safe_load(matches[0])
    except yaml.YAMLError as e:
        raise ManifestError(f"manifest YAML parse error: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError("manifest body is not a mapping")
    try:
        m = IntegrationManifest(**data)
    except ValidationError as e:
        raise ManifestError(f"manifest schema invalid: {e}") from e
    _enforce_url(m.register.url, allowlist, allow_wss=False)
    _enforce_url(m.connection.url, allowlist, allow_wss=True)
    if m.connection.token_refresh_url:
        _enforce_url(m.connection.token_refresh_url, allowlist, allow_wss=False)
    return m
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manifest.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/integration/manifest.py tests/unit/test_manifest.py
git commit -m "feat(integration): agent-integration manifest model + strict extraction"
```

---

## Phase 2 — Crypto + data model

### Task 5: Add cryptography dependency + Fernet credential crypto

**Files:**
- Modify: `pyproject.toml`
- Create: `src/integration/crypto.py`
- Test: `tests/unit/test_integration_crypto.py` (create)

- [ ] **Step 1: Add dependency**

In `pyproject.toml` `dependencies` list, after `"argon2-cffi>=23.1",` add:

```python
    "cryptography>=42.0", # 平台接入凭证加密(Fernet)
```

Run: `uv sync`
Expected: cryptography installed

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_integration_crypto.py`:

```python
"""Fernet credential crypto round-trip + key isolation."""
from __future__ import annotations

import pytest

from src.integration.crypto import decrypt_secret, encrypt_secret


def test_round_trip(monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "unit-test-secret")
    token = encrypt_secret("pairing-code-abc123")
    assert isinstance(token, bytes)
    assert token != b"pairing-code-abc123"
    assert decrypt_secret(token) == "pairing-code-abc123"


def test_wrong_key_fails(monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "key-A")
    token = encrypt_secret("x")
    monkeypatch.setenv("INTEGRATION_SECRET", "key-B")
    with pytest.raises(Exception):
        decrypt_secret(token)


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("INTEGRATION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        encrypt_secret("x")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_integration_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: src.integration.crypto`

- [ ] **Step 4: Implement crypto**

Create `src/integration/crypto.py`:

```python
"""Per-row credential encryption for platform_integration.

Key source: env INTEGRATION_SECRET, derived to a 32-byte urlsafe-b64
Fernet key. Intentionally separate from SESSION_SECRET so a session-key
leak does not expose stored pairing tokens (spec §Security Model).
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

_ENV = "INTEGRATION_SECRET"


def _fernet() -> Fernet:
    secret = os.getenv(_ENV)
    if not secret:
        raise RuntimeError(f"missing env var {_ENV}")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    return _fernet().decrypt(token).decode("utf-8")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_integration_crypto.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/integration/crypto.py tests/unit/test_integration_crypto.py
git commit -m "feat(integration): Fernet credential crypto + cryptography dep"
```

### Task 6: PlatformIntegration model + migration

**Files:**
- Modify: `src/models/schemas.py`
- Create: `src/db/migrations/versions/0008_platform_integration.py`
- Test: `tests/unit/test_platform_integration_model.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_platform_integration_model.py`:

```python
"""platform_integration model: persists + status enum values."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_platform_integration_persists(db_session):
    from src.models.schemas import IntegrationStatus, PlatformIntegration, User
    admin = User(id=uuid4(), name="a", email="adm@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()
    row = PlatformIntegration(
        id=uuid4(),
        platform_name="ExamplePlatform",
        manifest_snapshot={"version": 1, "platform": "ExamplePlatform"},
        status=IntegrationStatus.draft,
        created_by=admin.id,
        pairing_secret_ciphertext=None,
        token_refresh_meta=None,
    )
    db_session.add(row)
    await db_session.commit()
    got = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == row.id)
    )).scalars().first()
    assert got.status == IntegrationStatus.draft
    assert got.platform_name == "ExamplePlatform"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_platform_integration_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlatformIntegration'`

- [ ] **Step 3: Add model**

In `src/models/schemas.py`, after `MessageRole` enum (line 27) add:

```python
class IntegrationStatus(str, Enum):
    draft = "draft"
    active = "active"
    degraded = "degraded"
    disabled = "disabled"
```

At end of file add:

```python
class PlatformIntegration(Base):
    __tablename__ = "platform_integration"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    platform_name: Mapped[str] = mapped_column(String(200))
    manifest_snapshot: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        SAEnum(IntegrationStatus, name="integration_status"),
        default=IntegrationStatus.draft,
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"),
    )
    pairing_secret_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    token_refresh_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
```

Add `LargeBinary` to the sqlalchemy import:

```python
from sqlalchemy import (
    BIGINT, Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer,
    LargeBinary, String, Text, func,
)
```

- [ ] **Step 4: Write the migration**

Create `src/db/migrations/versions/0008_platform_integration.py`:

```python
"""platform_integration table.

Revision ID: 0008_platform_integration
Revises: 0007_user_is_admin
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_platform_integration"
down_revision = "0007_user_is_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_integration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform_name", sa.String(200), nullable=False),
        sa.Column("manifest_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "degraded", "disabled",
                    name="integration_status"),
            nullable=False, server_default="draft",
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pairing_secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("token_refresh_meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_integration")
    sa.Enum(name="integration_status").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Apply migration + run tests**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/test_platform_integration_model.py -v`
Expected: migration applies; 1 PASS

- [ ] **Step 6: Commit**

```bash
git add src/models/schemas.py src/db/migrations/versions/0008_platform_integration.py tests/unit/test_platform_integration_model.py
git commit -m "feat(integration): platform_integration model + migration"
```

---

## Phase 3 — Chat tools + admin gate + HITL signal

### Task 7: Thread user context through registry + engine

**Files:**
- Modify: `src/core/tool_registry.py`
- Modify: `src/core/conversation_engine.py:33,71-72,198-200`
- Modify: `src/api/chat.py:99-115,205-224`
- Test: `tests/unit/test_tool_registry.py` (append), `tests/unit/test_conversation_engine.py` (append)

- [ ] **Step 1: Write the failing test (registry admin gate)**

Append to `tests/unit/test_tool_registry.py`:

```python
@pytest.mark.asyncio
async def test_admin_only_tool_hidden_and_blocked_for_non_admin():
    schema = {"name": "secret_tool", "description": "x", "parameters": {}}
    reg = ToolRegistry(
        {"secret_tool": (schema, _StubTool(return_value={"ok": True}))},
        admin_only={"secret_tool"},
    )
    # hidden from schema list for non-admin
    assert reg.schemas(is_admin=False) == []
    assert reg.schemas(is_admin=True) == [
        {"type": "function", "function": schema}
    ]
    # blocked at execute for non-admin
    out = await reg.execute("secret_tool", {}, session_id="s",
                            user_id="u", is_admin=False)
    assert out == {"ok": False, "error": "forbidden",
                   "message": "admin only: secret_tool"}
    out2 = await reg.execute("secret_tool", {}, session_id="s",
                             user_id="u", is_admin=True)
    assert out2 == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tool_registry.py::test_admin_only_tool_hidden_and_blocked_for_non_admin -v`
Expected: FAIL — `TypeError: __init__() got unexpected keyword 'admin_only'`

- [ ] **Step 3: Update ToolRegistry**

Replace `src/core/tool_registry.py` `__init__`, `schemas`, `execute` (lines 28-83) with:

```python
class ToolRegistry:
    def __init__(
        self, tools: dict[str, ToolEntry],
        *, admin_only: set[str] | None = None,
    ) -> None:
        self._tools = tools
        self._admin_only = admin_only or set()

    @classmethod
    def default(
        cls, *, mem, embedder, min_similarity: float, top_k: int,
        reranker=None, rerank_top_n: int = 5,
        integration_deps: "IntegrationToolDeps | None" = None,
    ) -> "ToolRegistry":
        tools: dict[str, ToolEntry] = {
            "search_documents": (
                TOOL_SCHEMA,
                SearchDocumentsTool(
                    mem=mem, embedder=embedder,
                    min_similarity=min_similarity, top_k=top_k,
                    reranker=reranker, rerank_top_n=rerank_top_n,
                ),
            ),
        }
        admin_only: set[str] = set()
        if integration_deps is not None:
            from src.tools.integration_tools import build_integration_tools
            for name, schema, tool in build_integration_tools(integration_deps):
                tools[name] = (schema, tool)
                admin_only.add(name)
        return cls(tools, admin_only=admin_only)

    def schemas(self, *, is_admin: bool = False) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": schema}
            for name, (schema, _) in self._tools.items()
            if is_admin or name not in self._admin_only
        ]

    async def execute(
        self, name: str, arguments: dict, *, session_id,
        user_id=None, is_admin: bool = False,
    ) -> dict:
        entry = self._tools.get(name)
        if not entry:
            log.warning("tool_registry.unknown name=%s", name)
            return {
                "ok": False, "error": "unknown_tool",
                "message": f"unknown tool: {name}",
            }
        if name in self._admin_only and not is_admin:
            log.warning("tool_registry.forbidden name=%s user=%s", name, user_id)
            return {
                "ok": False, "error": "forbidden",
                "message": f"admin only: {name}",
            }
        _, tool = entry
        try:
            return await tool.execute(
                session_id=session_id, user_id=user_id, **arguments,
            )
        except TypeError:
            # Tools that don't accept user_id (e.g. search_documents) —
            # call without it for backward compatibility.
            try:
                return await tool.execute(session_id=session_id, **arguments)
            except Exception as e:
                log.exception("tool_registry.system_error name=%s", name)
                return {"ok": False, "error": "system", "message": str(e)[:200]}
        except Exception as e:
            log.exception("tool_registry.system_error name=%s", name)
            return {"ok": False, "error": "system", "message": str(e)[:200]}
```

Add near top of file (after line 16 import block), a forward-declared deps type import guard:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.tools.integration_tools import IntegrationToolDeps
```

- [ ] **Step 4: Update existing registry test expectations**

The existing `test_execute_dispatches_by_name_and_passes_session_id` asserts `tool.called_with == {"session_id": "sess-1", "q": "hi"}`. With the new `user_id=None` passthrough the stub now receives `user_id`. Update that assertion:

```python
    assert tool.called_with == {"session_id": "sess-1", "user_id": None, "q": "hi"}
```

(`_StubTool.execute` already accepts `**kwargs`, so it captures `user_id`.)

- [ ] **Step 5: Run registry tests**

Run: `uv run pytest tests/unit/test_tool_registry.py -v`
Expected: all PASS (existing + new)

- [ ] **Step 6: Thread context through engine**

In `src/core/conversation_engine.py`:

- Line 33, change signature:
```python
    async def handle_stream(self, *, session_id, message: str,
                            user_id=None, is_admin: bool = False,
                            **_ignored) -> AsyncIterator[StreamEvent]:
```
- Line 72, change `tools_for_llm = self.tools.schemas()` to:
```python
            tools_for_llm = self.tools.schemas(is_admin=is_admin)
```
- Lines 198-200, change the execute call to:
```python
                    result = await self.tools.execute(
                        acc["name"], args, session_id=session_id,
                        user_id=user_id, is_admin=is_admin,
                    )
```

- [ ] **Step 7: Pass context from chat route**

In `src/api/chat.py` `chat_stream` (line 220-224), the route already has `user_id` from `require_user`. Compute admin and pass:

```python
        from src.api.auth import is_current_user_admin
        is_admin = await is_current_user_admin(req_request, db)
        engine = _build_engine(db)
        events = engine.handle_stream(
            session_id=req.session_id,
            message=req.message,
            user_id=user_id,
            is_admin=is_admin,
        )
```

`is_current_user_admin` needs the `Request`. Add `req_request: Request` param to `chat_stream` and import `Request`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
...
    @router.post("/chat/stream")
    async def chat_stream(
        req: ChatRequest, req_request: Request,
        db: AsyncSession = Depends(get_db),
        user_id: UUID = Depends(require_user),
    ) -> SSEStreamingResponse:
```

- [ ] **Step 8: Run engine + chat tests**

Run: `uv run pytest tests/unit/test_conversation_engine.py tests/e2e/test_doc_qa.py -v`
Expected: PASS (existing behavior unchanged for non-admin / no integration tools)

- [ ] **Step 9: Commit**

```bash
git add src/core/tool_registry.py src/core/conversation_engine.py src/api/chat.py tests/unit/test_tool_registry.py
git commit -m "feat(tools): admin-only tool gating + user context threading"
```

### Task 8: Integration tools (fetch_manifest + request_pairing_code) + confirmation_required event

**Files:**
- Create: `src/tools/integration_tools.py`
- Modify: `src/api/sse.py:42-52`
- Modify: `src/core/conversation_engine.py` (confirmation_required handling)
- Test: `tests/unit/test_integration_tools.py` (create), `tests/unit/test_conversation_engine.py` (append)

- [ ] **Step 1: Add confirmation_required StreamEvent**

In `src/api/sse.py`, after the `citations` classmethod (line 52), add:

```python
    @classmethod
    def confirmation_required(
        cls, integration_id: str, token: str, summary: str,
    ) -> "StreamEvent":
        return cls(type="confirmation_required", data={
            "integration_id": integration_id,
            "token": token,
            "summary": summary,
        })
```

- [ ] **Step 2: Write the failing test (tools)**

Create `tests/unit/test_integration_tools.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_integration_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: src.tools.integration_tools`

- [ ] **Step 4: Implement integration tools**

Create `src/tools/integration_tools.py`:

```python
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
```

- [ ] **Step 5: Run tool tests**

Run: `uv run pytest tests/unit/test_integration_tools.py -v`
Expected: 2 PASS

- [ ] **Step 6: Write the failing engine test (confirmation_required short-circuits the loop)**

Append to `tests/unit/test_conversation_engine.py`:

```python
@pytest.mark.asyncio
async def test_confirmation_required_emits_event_and_stops_loop():
    """A tool result with status=confirmation_required must make the engine
    emit a confirmation_required StreamEvent and end the turn (no further
    LLM iteration / no auto-registration)."""
    from src.core.conversation_engine import ConversationEngine

    class _LLM:
        def __init__(self):
            self.calls = 0
        async def chat_stream(self, messages, tools=None):
            self.calls += 1
            from types import SimpleNamespace
            yield SimpleNamespace(
                text_delta="", finish_reason="tool_calls",
                tool_call_deltas=[SimpleNamespace(
                    index=0, id="tc1", name="request_pairing_code",
                    arguments_fragment='{"integration_id":"abc"}')],
            )

    class _Tools:
        def schemas(self, *, is_admin=False): return []
        async def execute(self, name, args, *, session_id, user_id=None,
                           is_admin=False):
            return {"ok": True, "status": "confirmation_required",
                    "integration_id": "abc", "token": "tok",
                    "summary": "平台: X"}

    class _Mem:
        async def save_user_message(self, *a, **k): pass
        async def save_assistant_message(self, *a, **k): pass
        async def count_documents_by_status(self, s): return {}
        async def list_documents(self, s): return []
        async def list_messages(self, s): return []

    llm = _LLM()
    eng = ConversationEngine(mem=_Mem(), llm=llm, tools=_Tools(),
                             persona="", max_tool_iterations=3)
    events = [e async for e in eng.handle_stream(
        session_id="s", message="接入", user_id="u", is_admin=True)]
    types = [e.type for e in events]
    assert "confirmation_required" in types
    ce = next(e for e in events if e.type == "confirmation_required")
    assert ce.data["integration_id"] == "abc"
    assert ce.data["token"] == "tok"
    # Loop must have stopped after the signal (only the 1 tool-call LLM call).
    assert llm.calls == 1
    assert types[-1] == "done"
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_conversation_engine.py::test_confirmation_required_emits_event_and_stops_loop -v`
Expected: FAIL — no `confirmation_required` event emitted (loop continues / fallback runs)

- [ ] **Step 8: Handle the signal in the engine**

In `src/core/conversation_engine.py`, inside the tool-call loop, right after the
`messages.append({"role": "tool", ...})` block (after line 215, still inside
`for acc in tool_call_acc.values():`), add a check. Replace the inner loop's
tail so that after appending the tool message it inspects the result:

```python
                    messages.append({
                        "role": "tool", "tool_call_id": acc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                    if result.get("status") == "confirmation_required":
                        yield StreamEvent.confirmation_required(
                            integration_id=result["integration_id"],
                            token=result["token"],
                            summary=result["summary"],
                        )
                        await self.mem.save_assistant_message(
                            session_id,
                            "已生成接入确认请求，请在前端确认后继续。",
                            citations=[],
                            routing={"template": template,
                                     "confirmation_required": True,
                                     "integration_id": result["integration_id"]},
                        )
                        yield StreamEvent.done()
                        return
                continue
```

(The `continue` keeps the existing control flow for non-signal tool calls.)

- [ ] **Step 9: Run engine tests**

Run: `uv run pytest tests/unit/test_conversation_engine.py -v`
Expected: all PASS (new test + existing)

- [ ] **Step 10: Commit**

```bash
git add src/tools/integration_tools.py src/api/sse.py src/core/conversation_engine.py tests/unit/test_integration_tools.py tests/unit/test_conversation_engine.py
git commit -m "feat(integration): fetch_manifest/request_pairing_code tools + HITL confirmation signal"
```

---

## Phase 4 — Registration execution + credential persistence

### Task 9: Registrar (confirmed register call + credential persist)

**Files:**
- Create: `src/integration/registrar.py`
- Test: `tests/unit/test_registrar.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_registrar.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registrar.py -v`
Expected: FAIL — `ModuleNotFoundError: src.integration.registrar`

- [ ] **Step 3: Implement registrar**

Create `src/integration/registrar.py`:

```python
"""Confirmed registration: the ONLY place that makes the side-effecting
register call. Reached only after HITL confirm (Task 10 endpoint)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
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
    row.token_refresh_meta = {"registered_at":
                              datetime.now(timezone.utc).isoformat()}
    await db.commit()
    log.info("integration.registered id=%s platform=%s",
             row.id, snap["platform"])
    return {"integration_id": str(row.id), "claim_url": claim_url,
            "status": "active"}
```

- [ ] **Step 4: Run registrar tests**

Run: `uv run pytest tests/unit/test_registrar.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/integration/registrar.py tests/unit/test_registrar.py
git commit -m "feat(integration): registrar — confirmed register + encrypted credential persist"
```

### Task 10: Integrations API (list / confirm / disable) + route mount

**Files:**
- Create: `src/api/integrations.py`
- Modify: `src/main.py`
- Modify: `src/api/chat.py` (wire IntegrationToolDeps into ToolRegistry.default)
- Test: `tests/unit/test_integrations_api.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_integrations_api.py`:

```python
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
    def __init__(self, uid): self.scope = {"session": {}}; self.session = {"user_id": str(uid)}


def _admin_req(uid): return _Req(uid)


def _find(router, name):
    for r in router.routes:
        if r.name == name:
            return r.endpoint
    raise AssertionError(f"route {name} not found")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_integrations_api.py -v`
Expected: FAIL — `ModuleNotFoundError: src.api.integrations`

- [ ] **Step 3: Implement integrations router**

Create `src/api/integrations.py`:

```python
"""Admin-only platform integration endpoints.

GET    /integrations               list integrations (status overview)
POST   /integrations/{id}/confirm  HITL gate → triggers registrar
POST   /integrations/{id}/disable  kill switch → connector drops on next tick
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_admin
from src.integration.registrar import RegistrarError, confirm_and_register
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)


class ConfirmBody(BaseModel):
    token: str


class IntegrationItem(BaseModel):
    id: UUID
    platform_name: str
    status: str


def make_integrations_router(*, sessionmaker) -> APIRouter:
    router = APIRouter(prefix="/integrations")

    async def get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as s:
            yield s

    async def _admin(request: Request,
                     db: AsyncSession = Depends(get_db)) -> UUID:
        return await require_admin(request, db)

    @router.get("", response_model=list[IntegrationItem], name="list")
    async def list_integrations(
        request: Request, db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        rows = (await db.execute(select(PlatformIntegration))).scalars().all()
        return [IntegrationItem(id=r.id, platform_name=r.platform_name,
                                status=str(r.status.value
                                           if hasattr(r.status, "value")
                                           else r.status))
                for r in rows]

    @router.post("/{integration_id}/confirm", name="confirm")
    async def confirm(
        integration_id: UUID, body: ConfirmBody, request: Request,
        db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        try:
            return await confirm_and_register(
                db, integration_id=integration_id, token=body.token)
        except RegistrarError as e:
            raise HTTPException(400, str(e))

    @router.post("/{integration_id}/disable", status_code=204, name="disable")
    async def disable(
        integration_id: UUID, request: Request,
        db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        row = (await db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.id == integration_id)
        )).scalars().first()
        if row is None:
            raise HTTPException(404, "integration not found")
        row.status = IntegrationStatus.disabled
        await db.commit()
        log.info("integration.disabled id=%s by=%s", integration_id, admin_id)

    return router
```

- [ ] **Step 4: Mount the router**

In `src/main.py`, find where `make_auth_router` / chat router are included and add (mirror existing include pattern; use the same `sessionmaker` passed to auth router):

```python
from src.api.integrations import make_integrations_router
...
    app.include_router(make_integrations_router(sessionmaker=sessionmaker))
```

(Place the import with the other `src.api.*` imports and the `include_router` call next to the auth router include.)

- [ ] **Step 5: Wire integration tools into the chat registry**

In `src/api/chat.py` `_build_engine` (line 99-115), pass integration deps so the admin-only tools exist in the chat loop:

```python
    def _build_engine(db: AsyncSession) -> ConversationEngine:
        from src.tools.integration_tools import IntegrationToolDeps
        mem = _build_memory(db)
        tools = ToolRegistry.default(
            mem=mem,
            embedder=deps.embedder,
            min_similarity=deps.min_similarity,
            top_k=deps.top_k,
            reranker=deps.reranker,
            rerank_top_n=deps.rerank_top_n,
            integration_deps=IntegrationToolDeps(
                sessionmaker=deps.sessionmaker),
        )
        return ConversationEngine(
            mem=mem, llm=deps.llm, tools=tools,
            persona=deps.persona.load(),
            max_tool_iterations=deps.settings.max_tool_iterations,
        )
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/test_integrations_api.py tests/e2e/test_doc_qa.py -v`
Expected: integrations PASS; existing e2e still PASS (non-admin path unaffected — admin tools hidden via `schemas(is_admin=False)`)

- [ ] **Step 7: Commit**

```bash
git add src/api/integrations.py src/main.py src/api/chat.py tests/unit/test_integrations_api.py
git commit -m "feat(integration): integrations API (list/confirm/disable) + chat wiring + route mount"
```

---

## Phase 5 — Persistent connector daemon

> Rationale: arq jobs are short-lived; a persistent bidirectional
> connection does not fit the job model. The connector is a standalone
> asyncio daemon (`python -m src.connector.main`), separate process from
> the API (spec:聊天 loop 请求级,持久连接必须独立长驻).

### Task 11: Inbound command security (schema + capability allowlist + fixed handlers)

**Files:**
- Create: `src/connector/__init__.py`
- Create: `src/connector/inbound.py`
- Test: `tests/unit/test_inbound.py` (create)

- [ ] **Step 1: Create package marker**

Create `src/connector/__init__.py`:

```python
```

(empty)

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_inbound.py`:

```python
"""Inbound command guard: default-deny, capability allowlist, fixed
minimal handlers, strict schema. No handler may touch tenant data."""
from __future__ import annotations

import pytest

from src.connector.inbound import InboundError, handle_inbound


@pytest.mark.asyncio
async def test_ping_allowed_when_declared():
    out = await handle_inbound({"type": "ping"},
                               declared_capabilities=["ping"])
    assert out == {"type": "pong"}


@pytest.mark.asyncio
async def test_request_status_allowed_when_declared():
    out = await handle_inbound({"type": "request_status"},
                               declared_capabilities=["request_status"])
    assert out["type"] == "status"
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_command_not_declared_rejected():
    with pytest.raises(InboundError):
        await handle_inbound({"type": "ping"}, declared_capabilities=[])


@pytest.mark.asyncio
async def test_unknown_command_type_rejected():
    with pytest.raises(InboundError):
        await handle_inbound({"type": "exec_shell", "cmd": "rm -rf /"},
                             declared_capabilities=["exec_shell"])


@pytest.mark.asyncio
async def test_malformed_message_rejected():
    with pytest.raises(InboundError):
        await handle_inbound("not-a-dict", declared_capabilities=["ping"])
    with pytest.raises(InboundError):
        await handle_inbound({"no_type": 1}, declared_capabilities=["ping"])
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_inbound.py -v`
Expected: FAIL — `ModuleNotFoundError: src.connector.inbound`

- [ ] **Step 4: Implement inbound guard**

Create `src/connector/inbound.py`:

```python
"""Inbound command handling — the bidirectional-connection risk surface.

Default deny. A command runs ONLY if:
  1. message is a dict with a string `type`
  2. that type is in the integration's manifest inbound_capabilities
  3. that type has a built-in handler here (a tiny, fixed set)

Handlers are capability-minimal: they NEVER read tenant documents,
NEVER execute arbitrary code, NEVER touch the DB. They answer liveness
only. Anything else → InboundError (logged, connection kept, command
dropped).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class InboundError(Exception):
    pass


async def _h_ping(_msg: dict) -> dict:
    return {"type": "pong"}


async def _h_request_status(_msg: dict) -> dict:
    return {"type": "status", "ok": True}


# The COMPLETE set of things an external platform may ever ask this
# system to do. Adding to this dict is the only way to grant a new
# inbound capability — reviewed deliberately, never data-touching.
_HANDLERS = {
    "ping": _h_ping,
    "request_status": _h_request_status,
}


async def handle_inbound(message, *, declared_capabilities: list[str]) -> dict:
    if not isinstance(message, dict):
        raise InboundError("message is not an object")
    cmd = message.get("type")
    if not isinstance(cmd, str):
        raise InboundError("message.type missing or not a string")
    if cmd not in declared_capabilities:
        raise InboundError(f"command {cmd!r} not in declared capabilities")
    handler = _HANDLERS.get(cmd)
    if handler is None:
        raise InboundError(f"no handler for command {cmd!r}")
    return await handler(message)
```

- [ ] **Step 5: Run inbound tests**

Run: `uv run pytest tests/unit/test_inbound.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/connector/__init__.py src/connector/inbound.py tests/unit/test_inbound.py
git commit -m "feat(connector): default-deny inbound command guard"
```

### Task 12: Connection lifecycle (websocket + heartbeat + reconnect + kill switch)

**Files:**
- Modify: `pyproject.toml` (add `websockets`)
- Create: `src/connector/connection.py`
- Test: `tests/unit/test_connection.py` (create)

- [ ] **Step 1: Add dependency**

In `pyproject.toml` `dependencies`, after the `cryptography` line add:

```python
    "websockets>=12.0", # 平台持久连接(connector)
```

Run: `uv sync`
Expected: websockets installed

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_connection.py`:

```python
"""IntegrationConnection: handshake, inbound dispatch, kill switch.

Uses a real in-process websockets server so the transport path is
exercised, not mocked away."""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from src.connector.connection import IntegrationConnection


@pytest.mark.asyncio
async def test_ping_roundtrip_and_kill_switch():
    received: list[dict] = []

    async def server(ws):
        async for raw in ws:
            received.append(json.loads(raw))
            await ws.send(json.dumps({"type": "ping"}))

    async with websockets.serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        stop = asyncio.Event()
        conn = IntegrationConnection(
            integration_id="i1",
            url=f"ws://127.0.0.1:{port}",
            declared_capabilities=["ping"],
            heartbeat_seconds=0.2,
            should_stop=lambda: stop.is_set(),
        )
        task = asyncio.create_task(conn.run())
        await asyncio.sleep(0.6)        # let heartbeat + pong exchange happen
        stop.set()                       # kill switch
        await asyncio.wait_for(task, timeout=2)

    # server saw at least one heartbeat, and conn replied pong to its ping
    assert any(m.get("type") == "heartbeat" for m in received)
    assert any(m.get("type") == "pong" for m in received)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: src.connector.connection`

- [ ] **Step 4: Implement connection**

Create `src/connector/connection.py`:

```python
"""One persistent connection to one external platform.

websocket transport only in this version (manifest may also declare
sse/poll — those raise NotImplementedError until a later iteration;
flagged explicitly rather than silently mishandled).

Lifecycle: connect → loop{ send heartbeat every N s; on inbound msg run
the inbound guard and send its reply } → on drop: exponential backoff
reconnect → exit promptly when should_stop() (kill switch / disabled)."""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

from src.connector.inbound import InboundError, handle_inbound

log = logging.getLogger(__name__)

_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0


class IntegrationConnection:
    def __init__(self, *, integration_id: str, url: str,
                 declared_capabilities: list[str],
                 heartbeat_seconds: float,
                 should_stop) -> None:
        self.integration_id = integration_id
        self.url = url
        self.declared_capabilities = declared_capabilities
        self.heartbeat_seconds = heartbeat_seconds
        self._should_stop = should_stop

    async def run(self) -> None:
        backoff = _BACKOFF_START
        while not self._should_stop():
            try:
                await self._session()
                backoff = _BACKOFF_START
            except Exception as e:  # noqa: BLE001 — connector must not die
                log.warning("connector id=%s session ended: %s",
                            self.integration_id, e)
            if self._should_stop():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
        log.info("connector id=%s stopped", self.integration_id)

    async def _session(self) -> None:
        async with websockets.connect(self.url) as ws:
            log.info("connector id=%s connected", self.integration_id)
            hb = asyncio.create_task(self._heartbeat(ws))
            try:
                while not self._should_stop():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    await self._on_message(ws, raw)
            finally:
                hb.cancel()

    async def _heartbeat(self, ws) -> None:
        while not self._should_stop():
            await ws.send(json.dumps({"type": "heartbeat"}))
            await asyncio.sleep(self.heartbeat_seconds)

    async def _on_message(self, ws, raw) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("connector id=%s dropped non-JSON inbound",
                        self.integration_id)
            return
        try:
            reply = await handle_inbound(
                msg, declared_capabilities=self.declared_capabilities)
        except InboundError as e:
            log.warning("connector id=%s rejected inbound: %s",
                        self.integration_id, e)
            return
        await ws.send(json.dumps(reply))
```

- [ ] **Step 5: Run connection test**

Run: `uv run pytest tests/unit/test_connection.py -v`
Expected: 1 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/connector/connection.py tests/unit/test_connection.py
git commit -m "feat(connector): websocket connection lifecycle + heartbeat + kill switch"
```

### Task 12.5: Token refresh (spec error-table parity)

> Closes the spec gap: "token 刷新失败 → 标记 degraded 并告警". Refresh
> contract (explicit assumption): the register / refresh response may
> include `expires_in` (seconds) and the manifest declares
> `connection.token_refresh_url`. Refresh = POST current pairing_code to
> that url, expect `{pairing_code, expires_in}`. No expiry stored → no-op
> (a platform that never expires tokens needs no refresh).

**Files:**
- Modify: `src/integration/registrar.py` (persist expiry + refresh url)
- Create: `src/connector/token_refresh.py`
- Test: `tests/unit/test_token_refresh.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_token_refresh.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_token_refresh.py -v`
Expected: FAIL — `ModuleNotFoundError: src.connector.token_refresh`

- [ ] **Step 3: Persist expiry in the registrar**

In `src/integration/registrar.py`, change the datetime import to include
`timedelta`:

```python
from datetime import datetime, timedelta, timezone
```

Replace the credential-persist tail of `confirm_and_register` (the block
from `row.pairing_secret_ciphertext = encrypt_secret(pairing_code)` to the
`return {...}`) with:

```python
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
```

(The Task 9 happy-path test's fake_post returns no `expires_in`, so `meta`
stays `{"registered_at": ...}` and that test remains green unchanged.)

- [ ] **Step 4: Implement token_refresh**

Create `src/connector/token_refresh.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_token_refresh.py tests/unit/test_registrar.py -v`
Expected: token_refresh 4 PASS; registrar 4 PASS (unchanged)

- [ ] **Step 6: Commit**

```bash
git add src/integration/registrar.py src/connector/token_refresh.py tests/unit/test_token_refresh.py
git commit -m "feat(connector): token refresh — rotate secret, degrade on failure"
```

### Task 13: Connector daemon (poll active rows, manage connections)

**Files:**
- Create: `src/connector/main.py`
- Test: `tests/unit/test_connector_main.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_connector_main.py`:

```python
"""Supervisor: starts a connection per active row, stops it when the row
leaves active (disabled kill switch)."""
from __future__ import annotations

import asyncio
import contextlib
from uuid import uuid4

import pytest

from src.connector.main import ConnectorSupervisor
from src.models.schemas import IntegrationStatus, PlatformIntegration, User


@contextlib.asynccontextmanager
async def _sm(session):
    """Test sessionmaker: yield the shared fixture session, never close it."""
    yield session


@pytest.mark.asyncio
async def test_supervisor_starts_and_stops_per_status(db_session, monkeypatch):
    admin = User(id=uuid4(), name="a", email="s@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()
    row = PlatformIntegration(
        id=uuid4(), platform_name="P",
        manifest_snapshot={"connection": {"transport": "websocket",
            "url": "ws://127.0.0.1:1", "heartbeat_seconds": 30},
            "inbound_capabilities": ["ping"]},
        status=IntegrationStatus.active, created_by=admin.id)
    db_session.add(row)
    await db_session.commit()

    started: list[str] = []
    stopped: list[str] = []

    class _FakeConn:
        def __init__(self, *, integration_id, **kw):
            self.integration_id = integration_id
        async def run(self):
            started.append(self.integration_id)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.append(self.integration_id)
                raise

    monkeypatch.setattr("src.connector.main.IntegrationConnection", _FakeConn)
    sup = ConnectorSupervisor(sessionmaker=lambda: _sm(db_session),
                              poll_seconds=0.1)
    sup_task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.3)
    assert str(row.id) in started

    row.status = IntegrationStatus.disabled
    await db_session.commit()
    await asyncio.sleep(0.4)
    assert str(row.id) in stopped

    sup.stop()
    await asyncio.wait_for(sup_task, timeout=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_connector_main.py -v`
Expected: FAIL — `ModuleNotFoundError: src.connector.main`

- [ ] **Step 3: Implement supervisor + entrypoint**

Create `src/connector/main.py`:

```python
"""Connector daemon entrypoint.

Run as a separate process:
    uv run python -m src.connector.main

Polls platform_integration for status=active rows. For each, runs one
IntegrationConnection. When a row leaves active (disabled kill switch /
degraded), its connection task is cancelled. should_stop closures read
a per-row flag the poller updates, so kill-switch latency ≤ poll_seconds.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from src.connector.connection import IntegrationConnection
from src.connector.token_refresh import refresh_if_due
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)


class ConnectorSupervisor:
    def __init__(self, *, sessionmaker, poll_seconds: float = 5.0) -> None:
        self._sessionmaker = sessionmaker
        self._poll = poll_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_ids: set[str] = set()
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def _active_rows(self) -> list[PlatformIntegration]:
        async with self._sessionmaker() as db:
            return list((await db.execute(
                select(PlatformIntegration).where(
                    PlatformIntegration.status == IntegrationStatus.active)
            )).scalars().all())

    async def _refresh_due(self) -> None:
        """Per-poll token refresh. refresh_if_due is a no-op for rows
        without a stored expiry, so this is cheap; on failure it flips the
        row to `degraded`, which the connection-management pass below then
        treats exactly like the kill switch (drops the connection)."""
        async with self._sessionmaker() as db:
            rows = list((await db.execute(
                select(PlatformIntegration).where(
                    PlatformIntegration.status == IntegrationStatus.active)
            )).scalars().all())
            for r in rows:
                try:
                    await refresh_if_due(db, r)
                except Exception:  # noqa: BLE001 — supervisor must not die
                    log.exception("refresh pass error id=%s", r.id)

    async def run(self) -> None:
        while not self._stop:
            await self._refresh_due()
            rows = await self._active_rows()
            now_active = {str(r.id) for r in rows}

            for r in rows:
                rid = str(r.id)
                if rid in self._tasks:
                    continue
                conn = IntegrationConnection(
                    integration_id=rid,
                    url=r.manifest_snapshot["connection"]["url"],
                    declared_capabilities=r.manifest_snapshot.get(
                        "inbound_capabilities", []),
                    heartbeat_seconds=r.manifest_snapshot["connection"].get(
                        "heartbeat_seconds", 30),
                    should_stop=lambda rid=rid: (
                        self._stop or rid not in self._active_ids),
                )
                self._active_ids.add(rid)
                self._tasks[rid] = asyncio.create_task(conn.run())
                log.info("supervisor started connection id=%s", rid)

            # Stop connections whose row left active.
            for rid in list(self._tasks):
                if rid not in now_active:
                    self._active_ids.discard(rid)
                    self._tasks[rid].cancel()
                    self._tasks.pop(rid)
                    log.info("supervisor stopped connection id=%s", rid)
            self._active_ids = now_active & self._active_ids | (
                now_active & set(self._tasks))

            await asyncio.sleep(self._poll)

        for t in self._tasks.values():
            t.cancel()


def main() -> None:  # pragma: no cover - process entrypoint
    import logging as _l

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.config import load_config
    from src.db.session import make_engine, make_sessionmaker

    _l.basicConfig(level=_l.INFO)
    cfg = load_config()
    engine = make_engine(cfg.db.url)
    sm: async_sessionmaker = make_sessionmaker(engine)
    sup = ConnectorSupervisor(sessionmaker=sm)
    try:
        asyncio.run(sup.run())
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run supervisor test**

Run: `uv run pytest tests/unit/test_connector_main.py -v`
Expected: 1 PASS

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all green (ruff debt policy: 0 — see commit 1d3ea4e)

- [ ] **Step 6: Commit**

```bash
git add src/connector/main.py tests/unit/test_connector_main.py
git commit -m "feat(connector): supervisor daemon — per-active-row connection lifecycle"
```

---

## Phase 6 — Docs

### Task 14: Operator docs (env vars, running the connector)

**Files:**
- Modify: `README.md` (append a section)
- Test: none (docs)

- [ ] **Step 1: Append operator section to README.md**

Add a `## 平台接入(remote-manifest integration)` section documenting:

```markdown
## 平台接入(remote-manifest integration)

管理员专用能力:聊天里发 `接入 X: https://.../SKILL.md`,agent 校验
远程清单 → 返回确认请求 → 前端确认 → 系统注册并维持持久连接。

必需环境变量:
- `INTEGRATION_HOST_ALLOWLIST` — 逗号分隔的允许域名(空 = 拒绝所有拉取)
- `INTEGRATION_SECRET` — 凭证加密密钥(独立于 SESSION_SECRET)

设管理员:`UPDATE users SET is_admin = true WHERE email = '...';`

运行连接守护进程(独立于 API 进程):
    uv run python -m src.connector.main

熔断:`POST /integrations/{id}/disable`(≤ poll 周期内断连)。
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: operator guide for remote-manifest platform integration"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task(s) |
|---|---|
| Locked #6 admin-only | Task 1, 2, 7 (gate), 10 (endpoints) |
| Locked #8 admin prerequisite | Task 1, 2 |
| Manifest 契约 (approach A, prose not control flow) | Task 4 |
| 聊天 loop 工具 + admin gate | Task 7, 8, 10(step5) |
| HITL 机制 (refined: signal + confirm endpoint) | Task 8 (signal), 10 (confirm) |
| Data flow 1–5 | Task 8 (1–3), 9+10 (4), 13 (5) |
| Data model platform_integration | Task 6 |
| safe_fetch SSRF | Task 3 |
| 凭证加密 (独立密钥) | Task 5, 9 |
| 入站命令默认拒 + 能力白名单 + 极小 handler | Task 11 |
| 熔断开关 | Task 10 (disable), 12/13 (drop) |
| 持久连接 worker (独立长驻) | Task 12, 13 |
| Error handling 表 | Task 3/4 (fetch/manifest), 9 (register non-2xx keeps draft, confirm-token expiry), 12 (backoff/reconnect), 12.5 (token 刷新失败 → degraded + 告警) |
| token 刷新 (spec error table) | Task 12.5 (refresh_if_due) + Task 13 (per-poll invocation) |
| Testing strategy | every Task has unit; e2e checks in Task 7/10; mock platform (Task 9/10), mock ws (Task 12) |
| Out of scope (per-user, cross-platform orchestration, platform-side protocol) | not implemented — intentional |

No spec requirement is left without a task.

**2. Placeholder scan:** No TBD/TODO; every code step has complete code; every command has expected output.

**3. Type consistency:** `sessionmaker` convention is consistent across `integration_tools.py`, `integrations.py`, `connector/main.py` — all use `async with sessionmaker() as s`; prod injects an `async_sessionmaker`, tests inject a non-closing CM factory (`_sm`). `confirmation_required` event shape `{integration_id, token, summary}` matches between `sse.py` (Task 8 step1), the tool result keys (Task 8 step4), and the engine emit (Task 8 step8). `PlatformIntegration` field names consistent across Tasks 6/8/9/10/12.5/13. `IntegrationStatus` values consistent (draft/active/degraded/disabled). `token_refresh_meta` keys consistent: `pending_confirm_token`/`expires_at` (pre-confirm, Task 8/9) vs `token_refresh_url`/`token_expires_at` (post-register, Task 9 step3 / 12.5).

**Scope:** all spec error-table rows now have a task (token refresh closed by Task 12.5 per user decision). No intentional deferrals remain.
