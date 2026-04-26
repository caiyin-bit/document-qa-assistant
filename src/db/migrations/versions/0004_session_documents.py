"""session_documents many-to-many

Lets a single document be visible in multiple sessions. Previously a
doc was owned by exactly one session via documents.session_id; that
forced re-uploading the same PDF to use it in a new conversation.

Backfill: every existing (documents.session_id, documents.id) pair
becomes one row in session_documents so current sessions still see
their docs after migration.

documents.session_id stays as the "creating session" for audit /
default-attach behaviour, but listing + retrieval now goes through
session_documents.

Revision ID: 0004_session_documents
Revises: 0003_hybrid_search_pg_trgm
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_session_documents"
down_revision = "0003_hybrid_search_pg_trgm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_documents",
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("document_id", UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "document_id"),
    )
    op.create_index(
        "ix_session_documents_session_id", "session_documents", ["session_id"],
    )
    op.create_index(
        "ix_session_documents_document_id", "session_documents", ["document_id"],
    )
    # Backfill from the implicit ownership column so legacy data still
    # resolves through the link table.
    op.execute(
        "INSERT INTO session_documents (session_id, document_id) "
        "SELECT session_id, id FROM documents "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_session_documents_document_id", table_name="session_documents")
    op.drop_index("ix_session_documents_session_id", table_name="session_documents")
    op.drop_table("session_documents")
