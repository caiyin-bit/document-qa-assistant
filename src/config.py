"""Config loading from YAML + environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    env: str
    log_level: str


class DbConfig(BaseModel):
    url: str


class LlmConfig(BaseModel):
    provider: str
    base_url: str
    model_id: str
    mode: str  # instant | thinking
    api_key_env: str
    api_key: str = ""  # resolved from env at load time


class EmbeddingConfig(BaseModel):
    model_path: str
    dim: int
    device: str  # cpu | cuda


class MemoryConfig(BaseModel):
    compress_trigger_threshold: int
    compress_keep_recent: int
    retrieve_top_k: int
    similarity_threshold: float


class ConversationConfig(BaseModel):
    max_tool_iterations: int


class PersonaConfig(BaseModel):
    identity_path: str
    soul_path: str


class AppUserConfig(BaseModel):
    default_user_id_env: str
    default_user_id: UUID | None = None


class Config(BaseModel):
    app: AppConfig
    db: DbConfig
    llm: LlmConfig
    embedding: EmbeddingConfig
    memory: MemoryConfig
    conversation: ConversationConfig
    persona: PersonaConfig
    app_user: AppUserConfig


def load_config(path: Path | str = "config.yaml") -> Config:
    """Load config.yaml and resolve env-backed fields."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = Config(**data)

    # Resolve LLM api_key from env
    api_key = os.getenv(cfg.llm.api_key_env)
    if not api_key:
        raise ValueError(f"Missing env var {cfg.llm.api_key_env} for LLM api_key")
    cfg.llm.api_key = api_key

    # Resolve default_user_id (may be empty during first setup, tolerate)
    uid_str = os.getenv(cfg.app_user.default_user_id_env)
    if uid_str:
        cfg.app_user.default_user_id = UUID(uid_str)

    # Allow runtime override of DB URL (used by docker-compose to point at the
    # `postgres` service name; yaml's localhost works in host-mode dev).
    db_url_env = os.getenv("DATABASE_URL")
    if db_url_env:
        cfg.db.url = db_url_env

    # Allow runtime override of LLM tunables (compose + README already advertise
    # these as overridable; before this patch they were silently ignored).
    base_url_env = os.getenv("MOONSHOT_BASE_URL")
    if base_url_env:
        cfg.llm.base_url = base_url_env
    model_id_env = os.getenv("MOONSHOT_MODEL_ID")
    if model_id_env:
        cfg.llm.model_id = model_id_env

    return cfg
