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
