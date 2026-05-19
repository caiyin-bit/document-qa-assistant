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
