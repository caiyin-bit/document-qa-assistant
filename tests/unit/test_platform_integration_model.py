"""platform_integration model: persists + status enum values."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_platform_integration_persists(db_session):
    from src.models.schemas import IntegrationStatus, PlatformIntegration, User
    admin = User(id=uuid4(), name="a", email="adm@x.com", is_admin=True)
    db_session.add(admin)
    await db_session.commit()
    row = PlatformIntegration(
        id=uuid4(),
        platform_name="ExamplePlatform",
        manifest_snapshot={"version": 1, "platform": "ExamplePlatform"},
        status=IntegrationStatus.draft,
        created_by=admin.id,
        pairing_secret_ciphertext=None,
        token_refresh_meta=None,
    )
    db_session.add(row)
    await db_session.commit()
    got = (await db_session.execute(
        select(PlatformIntegration).where(PlatformIntegration.id == row.id)
    )).scalars().first()
    assert got.status == IntegrationStatus.draft
    assert got.platform_name == "ExamplePlatform"
