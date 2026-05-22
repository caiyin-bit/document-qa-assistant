"""platform_integration table.

Revision ID: 0008_platform_integration
Revises: 0007_user_is_admin
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_platform_integration"
down_revision = "0007_user_is_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_integration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform_name", sa.String(200), nullable=False),
        sa.Column("manifest_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "degraded", "disabled",
                    name="integration_status"),
            nullable=False, server_default="draft",
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pairing_secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("token_refresh_meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_integration")
    sa.Enum(name="integration_status").drop(op.get_bind(), checkfirst=True)
