"""Async DB engine and sessionmaker factory."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, pool_size=5, max_overflow=5, echo=False)


def get_engine() -> AsyncEngine:
    """Return an AsyncEngine from DATABASE_URL env var."""
    db_url = os.environ["DATABASE_URL"]
    return create_async_engine(db_url, pool_size=5, max_overflow=5, echo=False)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session(
    sm: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Dependency-style context for FastAPI."""
    async with sm() as session:
        yield session
