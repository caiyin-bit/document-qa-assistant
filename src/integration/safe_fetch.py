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


def assert_url_allowed(url: str, *, allowlist: set[str],
                       schemes: set[str]) -> str:
    """Scheme + host-allowlist + DNS→blocked-IP guard. Raises
    SafeFetchError on any violation. Reusable by the connector
    (re-call on every reconnect to defeat DNS rebinding)."""
    parts = urlparse(url)
    if parts.scheme not in schemes:
        raise SafeFetchError(f"scheme not allowed ({parts.scheme!r}): {url}")
    host = (parts.hostname or "").lower()
    if not host or host not in {h.lower() for h in allowlist}:
        raise SafeFetchError(f"host not in allowlist: {host!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443)
    except socket.gaierror as e:
        raise SafeFetchError(f"DNS resolution failed: {host}") from e
    for info in infos:
        if _ip_is_blocked(info[4][0]):
            raise SafeFetchError(f"resolves to blocked IP: {info[4][0]}")
    return host


def _check_url(url: str, allowlist: set[str]) -> str:
    return assert_url_allowed(url, allowlist=allowlist, schemes={"https"})


async def _request(method: str, url: str, allowlist: set[str],
                   json_body: dict | None = None) -> httpx.Response:
    _check_url(url, allowlist)
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=_TIMEOUT_S,
    ) as client:
        async with client.stream(method, url, json=json_body) as resp:
            if 300 <= resp.status_code < 400:
                raise SafeFetchError(
                    f"redirect not allowed: {resp.status_code} {url}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_BYTES:
                    raise SafeFetchError("response too large")
                chunks.append(chunk)
            resp._content = b"".join(chunks)  # noqa: SLF001 — finalize body
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
