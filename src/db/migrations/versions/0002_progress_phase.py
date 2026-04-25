"""add documents.progress_phase column for granular ingestion progress

Adds a nullable string column the ingestion pipeline updates as it cycles
through stages per page (loading model → extracting → embedding → inserting).
The progress SSE endpoint surfaces this so the frontend can render
"正在向量化第 X / N 页" vs "正在加载模型…" vs etc, instead of a single
"解析中" that often looks frozen during BGE encode.

Revision ID: 0002_progress_phase
Revises: 0001_init
Create Date: 2026-04-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_progress_phase"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("progress_phase", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "progress_phase")
