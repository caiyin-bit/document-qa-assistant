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
