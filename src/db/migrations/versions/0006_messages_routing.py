"""add messages.routing JSONB column

Stores per-assistant-turn decision context: which template fired, how
many tool iterations ran, whether the premature-NO_MATCH guard fired,
which tools were invoked, etc. Read-only audit data; never used to
re-route a subsequent turn.

Revision ID: 0006_messages_routing
Revises: 0005_user_auth
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_messages_routing"
down_revision = "0005_user_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("routing", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "routing")
