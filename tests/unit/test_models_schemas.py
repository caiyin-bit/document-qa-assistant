"""Unit tests for SQLAlchemy model definitions in src.models.schemas."""
from __future__ import annotations


def test_message_model_has_routing_jsonb_field():
    from src.models.schemas import Message
    col = Message.__table__.c["routing"]
    assert col.nullable is True
    # JSONB is represented as sqlalchemy.dialects.postgresql.JSONB at the type level
    assert "JSONB" in str(col.type).upper()
