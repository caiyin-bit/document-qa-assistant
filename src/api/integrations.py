"""Admin-only platform integration endpoints.

GET    /integrations               list integrations (status overview)
POST   /integrations/{id}/confirm  HITL gate → triggers registrar
POST   /integrations/{id}/disable  kill switch → connector drops on next tick
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import require_admin
from src.integration.registrar import RegistrarError, confirm_and_register
from src.models.schemas import IntegrationStatus, PlatformIntegration

log = logging.getLogger(__name__)


class ConfirmBody(BaseModel):
    token: str
    session_id: UUID


class IntegrationItem(BaseModel):
    id: UUID
    platform_name: str
    status: str


def make_integrations_router(*, sessionmaker) -> APIRouter:
    router = APIRouter(prefix="/integrations")

    async def get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as s:
            yield s

    async def _admin(request: Request,
                     db: AsyncSession = Depends(get_db)) -> UUID:
        return await require_admin(request, db)

    @router.get("", response_model=list[IntegrationItem], name="list")
    async def list_integrations(
        request: Request, db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        rows = (await db.execute(select(PlatformIntegration))).scalars().all()
        return [IntegrationItem(id=r.id, platform_name=r.platform_name,
                                status=str(r.status.value
                                           if hasattr(r.status, "value")
                                           else r.status))
                for r in rows]

    @router.post("/{integration_id}/confirm", name="confirm")
    async def confirm(
        integration_id: UUID, body: ConfirmBody, request: Request,
        db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        try:
            return await confirm_and_register(
                db, integration_id=integration_id, token=body.token,
                session_id=str(body.session_id))
        except RegistrarError as e:
            raise HTTPException(400, str(e))

    @router.post("/{integration_id}/disable", status_code=204, name="disable")
    async def disable(
        integration_id: UUID, request: Request,
        db: AsyncSession = Depends(get_db),
        admin_id: UUID = Depends(_admin),
    ):
        row = (await db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.id == integration_id)
        )).scalars().first()
        if row is None:
            raise HTTPException(404, "integration not found")
        row.status = IntegrationStatus.disabled
        await db.commit()
        log.info("integration.disabled id=%s by=%s", integration_id, admin_id)

    return router
