"""user auth — email + password hash

Adds the columns needed to log in. Existing demo user gets backfilled
with a placeholder email so the UNIQUE constraint can land. The
password_hash is intentionally nullable: rows without one cannot log
in via password (demo user uses ALLOW_DEMO_LOGIN env path; future
OAuth users would also have NULL password_hash).

Revision ID: 0005_user_auth
Revises: 0004_session_documents
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_user_auth"
down_revision = "0004_session_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )
    # Backfill demo user so the email UNIQUE index can be created without
    # collisions. Other rows (none expected in dev, but be safe) get NULL.
    op.execute(
        "UPDATE users SET email = 'demo@example.com' "
        "WHERE id = '00000000-0000-0000-0000-000000000001' "
        "AND email IS NULL"
    )
    op.create_index(
        "ix_users_email", "users", ["email"], unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
