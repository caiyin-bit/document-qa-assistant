"""Unit tests for SQLAlchemy model definitions in src.models.schemas."""
from __future__ import annotations


def test_message_model_has_routing_jsonb_field():
    from src.models.schemas import Message
    col = Message.__table__.c["routing"]
    assert col.nullable is True
    # JSONB is represented as sqlalchemy.dialects.postgresql.JSONB at the type level
    assert "JSONB" in str(col.type).upper()


def test_user_has_is_admin_default_false():
    from src.models.schemas import User
    u = User(name="x")
    # SQLAlchemy column default applies at flush; the Python-side default
    # is declared so attribute is None until flush — assert the column exists.
    assert "is_admin" in User.__table__.columns
    assert User.__table__.columns["is_admin"].default.arg is False
