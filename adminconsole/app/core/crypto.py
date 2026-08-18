"""Encryption for runtime settings stored at rest (Graph client secret,
Authentik client secret, AD bind password — see app/core/settings_store.py).

FERNET_KEY is the one secret that lives in the environment; everything it
protects lives only in the encrypted DB column. If the key is missing or
invalid, encrypted settings are unreadable and the app degrades to
"not configured" for that section rather than crashing (checked by callers
via `is_configured()`, not by letting a Fernet exception propagate to a 500).
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet | None:
    key = get_settings().fernet_key.strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


def is_configured() -> bool:
    return _fernet() is not None


def encrypt(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY is not set or invalid — cannot encrypt settings.")
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """Returns None (never raises) on a missing key or a value that can't
    be decrypted (wrong/rotated key, corrupt row) — callers treat that the
    same as "not configured" rather than crashing the page that reads it."""
    if not ciphertext:
        return ""
    f = _fernet()
    if f is None:
        return None
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
