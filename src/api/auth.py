"""User auth — register / login / logout / me.

Cookie-based session via starlette SessionMiddleware (signed, stateless).
Password hashing: argon2-cffi.

Demo fallback: if `ALLOW_DEMO_LOGIN=true` (default in dev) and the
session has no user_id, the engine falls back to the seeded demo user.
This keeps the existing "open localhost:3000 and start chatting" UX
working while real registration is rolled out. Production should set
`ALLOW_DEMO_LOGIN=false` so /chat/* requires a real session.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.memory_service import DEMO_USER_ID
from src.models.schemas import User

log = logging.getLogger(__name__)

_PH = PasswordHasher()

# 6+ chars; we keep it minimal to stay friendly. Strength enforcement
# (entropy / breach lookup) is out of scope for this MVP.
_PASSWORD_MIN_LEN = 6


def _allow_demo_login() -> bool:
    return os.environ.get("ALLOW_DEMO_LOGIN", "true").lower() in ("1", "true", "yes")


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=_PASSWORD_MIN_LEN, max_length=128)
    name: str | None = Field(default=None, max_length=120)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    user_id: UUID
    email: str | None
    name: str
    is_demo: bool


def _set_session(request: Request, user_id: UUID) -> None:
    """starlette SessionMiddleware exposes request.session as a dict-like
    that gets serialised back into a signed cookie automatically."""
    request.session["user_id"] = str(user_id)


def _clear_session(request: Request) -> None:
    request.session.pop("user_id", None)


def make_auth_router(*, sessionmaker: async_sessionmaker[AsyncSession]) -> APIRouter:
    router = APIRouter(prefix="/auth")

    async def get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    @router.post("/register", response_model=MeResponse)
    async def register(
        body: RegisterBody, request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> MeResponse:
        email = body.email.lower().strip()
        # Check uniqueness — partial unique index in migration 0005 also
        # enforces this at DB level, but a friendly error is nicer than
        # a 500 from IntegrityError.
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalars().first() is not None:
            raise HTTPException(409, "该邮箱已注册")
        user = User(
            id=uuid4(),
            email=email,
            password_hash=_PH.hash(body.password),
            name=body.name or _name_from_email(email),
        )
        db.add(user)
        await db.commit()
        _set_session(request, user.id)
        return MeResponse(
            user_id=user.id, email=user.email, name=user.name, is_demo=False,
        )

    @router.post("/login", response_model=MeResponse)
    async def login(
        body: LoginBody, request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> MeResponse:
        email = body.email.lower().strip()
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        # Single error message for "wrong email" and "wrong password" so
        # we don't leak which existing emails are registered.
        if user is None or not user.password_hash:
            raise HTTPException(401, "邮箱或密码错误")
        try:
            _PH.verify(user.password_hash, body.password)
        except VerifyMismatchError:
            raise HTTPException(401, "邮箱或密码错误")
        # Opportunistic rehash if argon2 parameters have moved on.
        if _PH.check_needs_rehash(user.password_hash):
            user.password_hash = _PH.hash(body.password)
            await db.commit()
        _set_session(request, user.id)
        return MeResponse(
            user_id=user.id, email=user.email, name=user.name, is_demo=False,
        )

    @router.post("/logout", status_code=204)
    async def logout(request: Request) -> None:
        _clear_session(request)

    @router.get("/me", response_model=MeResponse)
    async def me(
        request: Request, db: AsyncSession = Depends(get_db),
    ) -> MeResponse:
        uid = current_user_id(request)
        if uid is None:
            raise HTTPException(401, "未登录")
        user = await db.get(User, uid)
        if user is None:
            _clear_session(request)
            raise HTTPException(401, "用户不存在")
        # is_demo signals "no real session — came in via the
        # ALLOW_DEMO_LOGIN fallback". A user who explicitly logged in
        # with demo's credentials still has session["user_id"] set, so
        # we look at the session, not at which user we landed on.
        is_demo = request.session.get("user_id") is None
        return MeResponse(
            user_id=user.id, email=user.email, name=user.name,
            is_demo=is_demo,
        )

    return router


def current_user_id(request: Request) -> UUID | None:
    """Resolve the active user. Cookie session > demo fallback (if enabled)
    > None. Used by chat / documents routes via Depends(require_user)."""
    raw = request.session.get("user_id") if "session" in request.scope else None
    if raw:
        try:
            return UUID(raw)
        except (ValueError, TypeError):
            return None
    if _allow_demo_login():
        return DEMO_USER_ID
    return None


def require_user(request: Request) -> UUID:
    """FastAPI dependency: 401 if no current user."""
    uid = current_user_id(request)
    if uid is None:
        raise HTTPException(401, "请先登录")
    return uid


def _name_from_email(email: str) -> str:
    local = re.split(r"[@+]", email, maxsplit=1)[0]
    return local[:120] or "user"
