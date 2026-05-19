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
import os

from sqlalchemy import select

from src.connector.connection import IntegrationConnection
from src.connector.token_refresh import refresh_if_due
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)


def _allowlist() -> set[str]:
    raw = os.getenv("INTEGRATION_HOST_ALLOWLIST", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


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
                    allowlist=_allowlist(),
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
