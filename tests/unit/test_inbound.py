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
