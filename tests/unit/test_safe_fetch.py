"""safe_fetch SSRF guard: scheme/allowlist/private-IP/redirect rejection."""
from __future__ import annotations

import httpx
import pytest

from src.integration.safe_fetch import (
    SafeFetchError,
    _ip_is_blocked,
    safe_fetch,
    safe_post,
)


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


def _mock_client(monkeypatch, handler):
    """Wire safe_fetch's internal httpx.AsyncClient to a MockTransport and
    no-op the SSRF guard (covered by its own tests). This exercises the
    REAL streamed-read + resp._content finalize path against the installed
    httpx — so an httpx upgrade that breaks .text/.json() after a streamed
    read fails here instead of silently breaking manifest fetch / register
    / token refresh."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def fake(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("src.integration.safe_fetch.httpx.AsyncClient", fake)
    monkeypatch.setattr("src.integration.safe_fetch._check_url",
                        lambda url, allowlist: "host")


@pytest.mark.asyncio
async def test_streamed_body_finalize_text_and_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/j":
            return httpx.Response(200, json={"pairing_code": "PC", "n": 1})
        return httpx.Response(200, text="hello-world")

    _mock_client(monkeypatch, handler)

    text = await safe_fetch("https://host/x", allowlist={"host"})
    assert text == "hello-world"

    resp = await safe_post("https://host/j", allowlist={"host"}, json_body={})
    assert resp.status_code == 200
    assert resp.json() == {"pairing_code": "PC", "n": 1}
    assert "PC" in resp.text  # .text also valid after the streamed finalize


@pytest.mark.asyncio
async def test_streaming_size_cap_aborts_on_real_path(monkeypatch):
    big = "x" * (300 * 1024)  # > 256 KB cap
    _mock_client(monkeypatch,
                 lambda request: httpx.Response(200, text=big))
    with pytest.raises(SafeFetchError):
        await safe_fetch("https://host/big", allowlist={"host"})
