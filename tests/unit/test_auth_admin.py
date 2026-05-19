"""require_admin dependency + is_current_user_admin resolution."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.auth import require_admin


class _Req:
    def __init__(self, scope_session: dict | None):
        self.scope = {"session": {}} if scope_session is not None else {}
        self.session = scope_session if scope_session is not None else {}


@pytest.mark.asyncio
async def test_require_admin_rejects_non_admin(db_session):
    from src.models.schemas import User
    from uuid import uuid4
    u = User(id=uuid4(), name="n", email="a@b.com", is_admin=False)
    db_session.add(u)
    await db_session.commit()
    req = _Req({"user_id": str(u.id)})
    with pytest.raises(HTTPException) as ei:
        await require_admin(req, db_session)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_allows_admin(db_session):
    from src.models.schemas import User
    from uuid import uuid4
    u = User(id=uuid4(), name="n", email="c@d.com", is_admin=True)
    db_session.add(u)
    await db_session.commit()
    req = _Req({"user_id": str(u.id)})
    assert await require_admin(req, db_session) == u.id


@pytest.mark.asyncio
async def test_require_admin_rejects_implicit_demo(db_session):
    # No user_id in session → demo fallback → must NOT be admin even if a
    # demo user row exists.
    req = _Req(None)
    with pytest.raises(HTTPException) as ei:
        await require_admin(req, db_session)
    assert ei.value.status_code in (401, 403)
