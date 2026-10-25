"""
Symmetric encryption helpers for credential storage.

Uses Fernet (AES-128-CBC via cryptography library) keyed from a
shared secret that must be configured identically on the scheduler
and any worker that needs to decrypt credentials at runtime.

Env:  CREDENTIAL_ENCRYPTION_KEY – base64-url-safe 32-byte key.
      If not provided, a deterministic key is derived from ADMIN_TOKEN
      via PBKDF2 so the system works out of the box (a warning is logged).
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _derive_key() -> bytes:
    """Return a 32-byte Fernet key."""
    explicit = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if explicit:
        raw = base64.urlsafe_b64decode(explicit)
        if len(raw) == 32:
            return base64.urlsafe_b64encode(raw)
        raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be 32 bytes (base64-url encoded)")
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        raise ValueError("Credential encryption requires CREDENTIAL_ENCRYPTION_KEY or ADMIN_TOKEN to be set")
    logger.warning(
        "CREDENTIAL_ENCRYPTION_KEY not set; deriving key from ADMIN_TOKEN. Set CREDENTIAL_ENCRYPTION_KEY for production use."
    )
    derived = hashlib.pbkdf2_hmac("sha256", admin_token.encode(), b"hydra-credential-salt", 100_000)
    return base64.urlsafe_b64encode(derived)


def encrypt_payload(data: dict[str, Any]) -> str:
    """Encrypt a dict to a Fernet token string."""
    from cryptography.fernet import Fernet

    f = Fernet(_derive_key())
    return f.encrypt(json.dumps(data).encode()).decode()


def decrypt_payload(token: str) -> dict[str, Any]:
    """Decrypt a Fernet token string back to a dict."""
    from cryptography.fernet import Fernet

    f = Fernet(_derive_key())
    return json.loads(f.decrypt(token.encode()).decode())
