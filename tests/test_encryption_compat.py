"""Stored credentials must stay readable across `cryptography` upgrades.

The existing tests only round-trip (encrypt then decrypt with the *same*
library version), which cannot notice an upgrade that changes the token
format or key handling. These tokens were produced by the code at the time
this file was written (cryptography 46.x); every later release must still
decrypt them. Do not regenerate them to make a failing test pass.
"""

import base64

import pytest
from cryptography.fernet import InvalidToken

from scheduler.utils import encryption

EXPLICIT_KEY = "aHlkcmEtZml4ZWQtdGVzdC1rZXktMDEyMzQ1Njc4OSE="
EXPLICIT_KEY_TOKEN = (
    "gAAAAABqyoJwYSdAT2Tw1MOHu35jRVP5QHCDPcwVQUA_c0SjbcMuYUXproetF2no-W42DYH-3eeol7rW3o2no9fSOTSkny9T6koCid6GFMTl1K89Zv"
    "WUvlCBLP8UDj5ZSpSb5013WSJRSDSTs9fMLLBbPQhiIPcrHA=="
)
EXPLICIT_KEY_PAYLOAD = {"username": "svc", "password": "p@ss word/é", "n": 1}

DERIVED_ADMIN_TOKEN = "canary-admin-token"
DERIVED_KEY_TOKEN = (
    "gAAAAABqyoJwtCpgnzZFexeUuIDJwVDAmASafl2i-C2GI8MR9XRLu1ELexVHsexQOtguxU0QO4MenbmRm6fM5PF1RuumoSRVxiLHILtsGcpiEYr970UI"
    "o8AWyQKPQAqbc-7lK6iswMRfG2rP7YfuDaojoTPQ_o7awW6QjbyJArkI3cCPyKQIlsk="
)
DERIVED_KEY_PAYLOAD = {"connection_uri": "postgresql://u:pw@db:5432/app", "nested": {"a": [1, 2, 3]}}


@pytest.fixture
def explicit_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", EXPLICIT_KEY)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)


@pytest.fixture
def derived_key(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", DERIVED_ADMIN_TOKEN)


def test_token_written_with_an_explicit_key_still_decrypts(explicit_key):
    assert encryption.decrypt_payload(EXPLICIT_KEY_TOKEN) == EXPLICIT_KEY_PAYLOAD


def test_token_written_with_a_key_derived_from_admin_token_still_decrypts(derived_key):
    """Pins the PBKDF2 derivation (sha256, salt, 100k iterations) as well as the Fernet format."""
    assert encryption.decrypt_payload(DERIVED_KEY_TOKEN) == DERIVED_KEY_PAYLOAD


def test_old_tokens_have_the_fernet_v1_layout():
    raw = base64.urlsafe_b64decode(EXPLICIT_KEY_TOKEN)
    assert raw[0] == 0x80  # Fernet version byte
    assert len(raw) > 1 + 8 + 16 + 32  # version + timestamp + IV + HMAC


def test_a_tampered_token_is_rejected(explicit_key):
    tampered = EXPLICIT_KEY_TOKEN[:-8] + ("A" if EXPLICIT_KEY_TOKEN[-8] != "A" else "B") + EXPLICIT_KEY_TOKEN[-7:]
    with pytest.raises(InvalidToken):
        encryption.decrypt_payload(tampered)


def test_the_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    with pytest.raises(InvalidToken):
        encryption.decrypt_payload(EXPLICIT_KEY_TOKEN)


def test_new_tokens_round_trip_and_are_not_identical(explicit_key):
    first = encryption.encrypt_payload(EXPLICIT_KEY_PAYLOAD)
    second = encryption.encrypt_payload(EXPLICIT_KEY_PAYLOAD)
    assert first != second  # random IV
    assert encryption.decrypt_payload(first) == encryption.decrypt_payload(second) == EXPLICIT_KEY_PAYLOAD
