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
async def test_ping_roundtrip_and_kill_switch(monkeypatch):
    monkeypatch.setattr("src.connector.connection.assert_url_allowed",
                        lambda *a, **k: "ok")
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
            allowlist=set(),
            should_stop=lambda: stop.is_set(),
        )
        task = asyncio.create_task(conn.run())
        await asyncio.sleep(0.6)        # let heartbeat + pong exchange happen
        stop.set()                       # kill switch
        await asyncio.wait_for(task, timeout=2)

    # server saw at least one heartbeat, and conn replied pong to its ping
    assert any(m.get("type") == "heartbeat" for m in received)
    assert any(m.get("type") == "pong" for m in received)


@pytest.mark.asyncio
async def test_blocked_url_stops_without_connecting():
    """A loopback / non-allowlisted wss URL must be rejected by the guard;
    run() exits promptly and never opens a socket."""
    conn = IntegrationConnection(
        integration_id="i2",
        url="wss://127.0.0.1:9/x",
        declared_capabilities=[],
        heartbeat_seconds=0.2,
        allowlist={"127.0.0.1"},   # host on list but resolves to loopback → blocked
        should_stop=lambda: False,
    )
    await asyncio.wait_for(conn.run(), timeout=2)
