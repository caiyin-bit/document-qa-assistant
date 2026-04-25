"""Tests for PersonaLoader."""

from pathlib import Path

from src.core.persona_loader import PersonaLoader


def test_load_returns_concatenated_identity_and_soul(tmp_path: Path):
    identity = tmp_path / "IDENTITY.md"
    soul = tmp_path / "SOUL.md"
    identity.write_text("# 身份\n你是助手。\n", encoding="utf-8")
    soul.write_text("# 风格\n简洁。\n", encoding="utf-8")

    loader = PersonaLoader(identity_path=identity, soul_path=soul)
    text = loader.load()

    assert "你是助手。" in text
    assert "简洁。" in text
    # IDENTITY 先于 SOUL
    assert text.index("你是助手。") < text.index("简洁。")


def test_load_is_cached(tmp_path: Path):
    identity = tmp_path / "IDENTITY.md"
    soul = tmp_path / "SOUL.md"
    identity.write_text("初版", encoding="utf-8")
    soul.write_text("soul", encoding="utf-8")

    loader = PersonaLoader(identity_path=identity, soul_path=soul)
    first = loader.load()

    # 文件改了,但 loader 缓存不变
    identity.write_text("新版", encoding="utf-8")
    second = loader.load()
    assert first == second

    # 显式 reload 才能拿到新内容
    loader.reload()
    third = loader.load()
    assert "新版" in third
