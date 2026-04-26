"""hybrid search via pg_trgm

Adds the lexical/keyword recall path used alongside pgvector cosine for
RRF (Reciprocal Rank Fusion). Pure vector recall misses on:
  - exact numbers ("6605亿") — embeddings smear digits together
  - proper nouns / IDs that are out-of-vocabulary for the embedder
  - rare technical terms

pg_trgm builds a character-trigram index (built-in, no Chinese tokenizer
needed). The `gin_trgm_ops` GIN index makes `content % :query` and
`similarity(content, :query)` lookups fast even on large chunk tables.
For Chinese, trigrams are character-level — coarse but covers the
exact-substring recall we need.

Revision ID: 0003_hybrid_search_pg_trgm
Revises: 0002_progress_phase
"""
from alembic import op

revision = "0003_hybrid_search_pg_trgm"
down_revision = "0002_progress_phase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_document_chunks_content_trgm "
        "ON document_chunks USING gin (content gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_trgm")
    # pg_trgm extension intentionally NOT dropped (may be shared with
    # other tools / migrations).
