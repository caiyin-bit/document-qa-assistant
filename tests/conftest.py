"""Shared pytest configuration. DB fixtures will be added in Task 1."""

from __future__ import annotations

from dotenv import load_dotenv

# Load .env at test session start so GEMINI_API_KEY etc. are available.
load_dotenv()

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    from src.core.memory_service import MemoryService
    from src.db.session import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import text
    engine = get_engine()
    Sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with Sessionmaker() as session:
        # Re-seed demo user. Tests rely on it as the implicit current
        # user (via require_user's demo fallback or DEMO_USER_ID); the
        # previous conftest dropped this seed which broke FK constraints
        # once we removed the auto-upsert from the route.
        await MemoryService(session).upsert_demo_user()
        try:
            yield session
        finally:
            # Test isolation: clear all data tables. CASCADE handles FK chain.
            # Order: chunks → documents → messages → sessions → users (children first)
            # but TRUNCATE ... CASCADE cuts the dependency.
            await session.execute(text(
                "TRUNCATE TABLE document_chunks, documents, messages, sessions, users "
                "RESTART IDENTITY CASCADE"
            ))
            await session.commit()
