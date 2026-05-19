"""Per-row credential encryption for platform_integration.

Key source: env INTEGRATION_SECRET, derived to a 32-byte urlsafe-b64
Fernet key. Intentionally separate from SESSION_SECRET so a session-key
leak does not expose stored pairing tokens (spec §Security Model).
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

_ENV = "INTEGRATION_SECRET"


def _fernet() -> Fernet:
    secret = os.getenv(_ENV)
    if not secret:
        raise RuntimeError(f"missing env var {_ENV}")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    return _fernet().decrypt(token).decode("utf-8")
