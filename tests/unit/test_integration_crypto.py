"""Fernet credential crypto round-trip + key isolation."""
from __future__ import annotations

import pytest

from src.integration.crypto import decrypt_secret, encrypt_secret


def test_round_trip(monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "unit-test-secret")
    token = encrypt_secret("pairing-code-abc123")
    assert isinstance(token, bytes)
    assert token != b"pairing-code-abc123"
    assert decrypt_secret(token) == "pairing-code-abc123"


def test_wrong_key_fails(monkeypatch):
    monkeypatch.setenv("INTEGRATION_SECRET", "key-A")
    token = encrypt_secret("x")
    monkeypatch.setenv("INTEGRATION_SECRET", "key-B")
    with pytest.raises(Exception):
        decrypt_secret(token)


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("INTEGRATION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        encrypt_secret("x")
