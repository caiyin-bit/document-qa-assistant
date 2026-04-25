from src.models.schemas import User, Session, Message, Document, DocumentChunk

def test_models_have_expected_columns():
    user_cols = {c.name for c in User.__table__.columns}
    assert {"id", "name", "created_at"} <= user_cols

    session_cols = {c.name for c in Session.__table__.columns}
    assert {"id", "user_id", "created_at", "last_active_at",
            "summary", "summary_until_message_id"} <= session_cols

    message_cols = {c.name for c in Message.__table__.columns}
    assert {"id", "session_id", "role", "content",
            "tool_calls", "tool_call_id", "citations", "created_at"} <= message_cols

    doc_cols = {c.name for c in Document.__table__.columns}
    assert {"id", "user_id", "session_id", "filename", "page_count",
            "byte_size", "status", "error_message", "progress_page",
            "uploaded_at", "ingestion_started_at"} <= doc_cols

    chunk_cols = {c.name for c in DocumentChunk.__table__.columns}
    assert {"id", "document_id", "page_no", "chunk_idx",
            "content", "content_embedding", "token_count"} <= chunk_cols

def test_document_chunk_cascades():
    fk = next(iter(DocumentChunk.__table__.foreign_keys))
    assert fk.ondelete == "CASCADE"
