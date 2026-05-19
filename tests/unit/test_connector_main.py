"""Supervisor: starts a connection per active row, stops it when the row
leaves active (disabled kill switch)."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.connector.main import ConnectorSupervisor
from src.db.session import get_engine
from src.models.schemas import IntegrationStatus, PlatformIntegration, User


@pytest.mark.asyncio
async def test_supervisor_starts_and_stops_per_status(db_session, monkeypatch):
    admin = User(id=uuid4(), name="a", email="s@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()
    row = PlatformIntegration(
        id=uuid4(), platform_name="P",
        manifest_snapshot={"connection": {"transport": "websocket",
            "url": "ws://127.0.0.1:1", "heartbeat_seconds": 30},
            "inbound_capabilities": ["ping"]},
        status=IntegrationStatus.active, created_by=admin.id)
    db_session.add(row)
    await db_session.commit()

    started: list[str] = []
    stopped: list[str] = []

    class _FakeConn:
        def __init__(self, *, integration_id, **kw):
            self.integration_id = integration_id
        async def run(self):
            started.append(self.integration_id)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.append(self.integration_id)
                raise

    monkeypatch.setattr("src.connector.main.IntegrationConnection", _FakeConn)
    # Real sessionmaker (independent session per `async with`, like prod):
    # the supervisor polls concurrently with this test, and a single shared
    # AsyncSession cannot be used by overlapping operations. Rows are
    # committed above so a separate session on the same DB sees them.
    sm = async_sessionmaker(get_engine(), expire_on_commit=False)
    sup = ConnectorSupervisor(sessionmaker=sm, poll_seconds=0.1)
    sup_task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.3)
    assert str(row.id) in started

    row.status = IntegrationStatus.disabled
    await db_session.commit()
    await asyncio.sleep(0.4)
    assert str(row.id) in stopped

    sup.stop()
    await asyncio.wait_for(sup_task, timeout=2)
