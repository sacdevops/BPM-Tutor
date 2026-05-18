"""Cryptographic helpers for encrypting sensitive data (API keys) at rest.

Keys are prefixed with 'enc:' so we can detect unencrypted legacy values.
The encryption key is derived from the app SECRET_KEY via SHA-256.
"""
from __future__ import annotations

import base64
import hashlib
import os


def _get_fernet():
    """Return a Fernet instance keyed from the app SECRET_KEY."""
    from cryptography.fernet import Fernet
    import config
    raw = hashlib.sha256(config.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return 'enc:<ciphertext>'."""
    if not plaintext:
        return plaintext
    if plaintext.startswith('enc:'):
        return plaintext          # already encrypted
    try:
        token = _get_fernet().encrypt(plaintext.encode()).decode()
        return f'enc:{token}'
    except Exception:
        return plaintext          # never crash — return as-is


def decrypt_value(stored: str) -> str:
    """Decrypt a value that was encrypted by :func:`encrypt_value`."""
    if not stored:
        return stored
    if not stored.startswith('enc:'):
        return stored             # legacy plaintext — return as-is
    try:
        return _get_fernet().decrypt(stored[4:].encode()).decode()
    except Exception:
        return ''                 # corrupted — return empty


def encrypt_api_key(key: str) -> str:
    return encrypt_value(key)


def decrypt_api_key(stored: str) -> str:
    return decrypt_value(stored)
