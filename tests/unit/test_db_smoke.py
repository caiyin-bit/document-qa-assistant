import pytest
from sqlalchemy import text
from src.db.session import get_engine

@pytest.mark.asyncio
async def test_migration_creates_all_tables():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        ))
        names = {row[0] for row in result.fetchall()}
        assert {"users", "sessions", "messages", "documents", "document_chunks"} <= names

@pytest.mark.asyncio
async def test_pgvector_extension_present():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'"))
        assert result.scalar() == "vector"
