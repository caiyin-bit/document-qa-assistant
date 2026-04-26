"""Tests for config loading."""

from pathlib import Path

from src.config import Config, load_config


def test_load_config_from_yaml(tmp_path: Path, monkeypatch):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        """
app:
  env: dev
  log_level: INFO
db:
  url: postgresql+asyncpg://postgres:postgres@localhost:5432/chat
llm:
  provider: deeprouter
  base_url: https://api.deeprouter.cn/v1
  model_id: gemini-2.5-flash
  mode: instant
  api_key_env: GEMINI_API_KEY
embedding:
  model_path: BAAI/bge-large-zh-v1.5
  dim: 1024
  device: cpu
memory:
  compress_trigger_threshold: 32
  compress_keep_recent: 16
  retrieve_top_k: 5
  similarity_threshold: 0.55
conversation:
  max_tool_iterations: 3
persona:
  identity_path: persona/IDENTITY.md
  soul_path: persona/SOUL.md
app_user:
  default_user_id_env: APP_USER_ID
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    monkeypatch.setenv("APP_USER_ID", "00000000-0000-0000-0000-000000000000")

    cfg: Config = load_config(yaml_path)

    assert cfg.llm.model_id == "gemini-2.5-flash"
    assert cfg.llm.api_key == "sk-test"
    assert cfg.embedding.dim == 1024
    assert cfg.memory.similarity_threshold == 0.55
    assert cfg.conversation.max_tool_iterations == 3
    assert str(cfg.app_user.default_user_id) == "00000000-0000-0000-0000-000000000000"


def test_missing_api_key_env_raises(tmp_path: Path, monkeypatch):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        """
app: {env: dev, log_level: INFO}
db: {url: postgresql+asyncpg://localhost/x}
llm:
  provider: deeprouter
  base_url: https://x
  model_id: x
  mode: instant
  api_key_env: MISSING_VAR
embedding: {model_path: x, dim: 1024, device: cpu}
memory: {compress_trigger_threshold: 32, compress_keep_recent: 16, retrieve_top_k: 5, similarity_threshold: 0.55}
conversation: {max_tool_iterations: 3}
persona: {identity_path: persona/IDENTITY.md, soul_path: persona/SOUL.md}
app_user: {default_user_id_env: APP_USER_ID}
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("MISSING_VAR", raising=False)
    monkeypatch.setenv("APP_USER_ID", "00000000-0000-0000-0000-000000000000")

    import pytest
    with pytest.raises(ValueError, match="MISSING_VAR"):
        load_config(yaml_path)


def test_memory_config_has_new_compress_keys(tmp_path, monkeypatch):
    """compress_trigger_threshold + compress_keep_recent replace session_history_limit."""
    import yaml
    from src.config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "app": {"env": "dev", "log_level": "INFO"},
        "db": {"url": "postgresql+asyncpg://x"},
        "llm": {
            "provider": "deeprouter", "base_url": "x",
            "model_id": "x", "mode": "instant", "api_key_env": "X_KEY",
        },
        "embedding": {"model_path": "x", "dim": 1024, "device": "cpu"},
        "memory": {
            "compress_trigger_threshold": 32,
            "compress_keep_recent": 16,
            "retrieve_top_k": 5,
            "similarity_threshold": 0.55,
        },
        "conversation": {"max_tool_iterations": 3},
        "persona": {"identity_path": "persona/IDENTITY.md", "soul_path": "persona/SOUL.md"},
        "app_user": {"default_user_id_env": "APP_USER_ID"},
    }))
    monkeypatch.setenv("X_KEY", "sk-test")
    cfg = load_config(cfg_path)
    assert cfg.memory.compress_trigger_threshold == 32
    assert cfg.memory.compress_keep_recent == 16
