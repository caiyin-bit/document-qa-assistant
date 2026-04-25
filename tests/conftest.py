"""Shared pytest configuration. DB fixtures will be added in Task 1."""

from __future__ import annotations

from dotenv import load_dotenv

# Load .env at test session start so MOONSHOT_API_KEY etc. are available.
load_dotenv()

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    from src.db.session import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    engine = get_engine()
    Sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with Sessionmaker() as session:
        yield session
        await session.rollback()
