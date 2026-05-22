"""users.is_admin — admin role for platform integration onboarding.

Revision ID: 0007_user_is_admin
Revises: 0006_messages_routing
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_user_is_admin"
down_revision = "0006_messages_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
