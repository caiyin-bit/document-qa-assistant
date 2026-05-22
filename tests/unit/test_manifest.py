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
