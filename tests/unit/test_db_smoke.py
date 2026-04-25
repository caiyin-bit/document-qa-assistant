"""Sanity check: models import and metadata reflects expected tables."""

from sqlalchemy import inspect

from src.models.schemas import Base, Session


def test_metadata_has_all_tables():
    table_names = set(Base.metadata.tables.keys())
    assert table_names == {
        "users",
        "contacts",
        "follow_ups",
        "todos",
        "sessions",
        "messages",
        "user_profiles",
    }


def test_session_has_summary_columns():
    # Columns come from ORM; this catches a forgotten rename or schema drift.
    cols = {c.name for c in inspect(Session).columns}
    assert "summary" in cols
    assert "summary_until_message_id" in cols
