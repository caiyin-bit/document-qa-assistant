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
from src.integration.safe_fetch import SafeFetchError, assert_url_allowed

log = logging.getLogger(__name__)

_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0


class _FatalConnectionError(Exception):
    """URL failed the SSRF guard — do not reconnect."""


class IntegrationConnection:
    def __init__(self, *, integration_id: str, url: str,
                 declared_capabilities: list[str],
                 heartbeat_seconds: float,
                 allowlist: set[str],
                 should_stop) -> None:
        self.integration_id = integration_id
        self.url = url
        self.declared_capabilities = declared_capabilities
        self.heartbeat_seconds = heartbeat_seconds
        self.allowlist = allowlist
        self._should_stop = should_stop

    async def run(self) -> None:
        backoff = _BACKOFF_START
        while not self._should_stop():
            try:
                await self._session()
                backoff = _BACKOFF_START
            except _FatalConnectionError:
                log.error("connector id=%s permanently stopped (blocked url)",
                          self.integration_id)
                break
            except Exception as e:  # noqa: BLE001 — connector must not die
                log.warning("connector id=%s session ended: %s",
                            self.integration_id, e)
            if self._should_stop():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
        log.info("connector id=%s stopped", self.integration_id)

    async def _session(self) -> None:
        try:
            assert_url_allowed(self.url, allowlist=self.allowlist,
                               schemes={"wss"})
        except SafeFetchError as e:
            log.error("connector id=%s blocked url %s: %s",
                      self.integration_id, self.url, e)
            raise _FatalConnectionError(str(e)) from e
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
