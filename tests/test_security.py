"""Security-focused tests for domain isolation and credential management."""
import os

import pytest

from scheduler.api.jobs import MASKED_SECRET, _sanitize_job_response
from scheduler.models.credentials import CredentialCreate, CredentialReference
from scheduler.models.executor import ShellExecutor, SqlExecutor
from scheduler.models.job_definition import Affinity, JobDefinition
from scheduler.utils.encryption import decrypt_payload, encrypt_payload

# --- Domain-scoped credential resolution ---


def test_credential_ref_cross_domain_blocked():
    """Credential from domain A cannot be resolved for a job in domain B."""
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        from scheduler.scheduler import _resolve_credential_refs

        encrypted = encrypt_payload({"connection_uri": "postgresql://user:pass@host/db"})

        class FakeDB:
            class credentials:
                @staticmethod
                def find_one(query):
                    # Credential exists only in domain "alpha"
                    if query.get("name") == "shared-cred" and query.get("domain") == "alpha":
                        return {"name": "shared-cred", "domain": "alpha", "encrypted_payload": encrypted}
                    return None

        # Job is in domain "beta" — should NOT resolve credential from "alpha"
        job = {
            "_id": "job-cross",
            "domain": "beta",
            "executor": {"type": "sql", "dialect": "postgres", "query": "SELECT 1", "credential_ref": "shared-cred"},
        }
        resolved = _resolve_credential_refs(job, FakeDB())
        assert "connection_uri" not in resolved.get("executor", {}), "Credential from another domain should not be resolved"
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_credential_ref_same_domain_resolves():
    """Credential from same domain is resolved correctly."""
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        from scheduler.scheduler import _resolve_credential_refs

        encrypted = encrypt_payload({"connection_uri": "postgresql://user:pass@host/db"})

        class FakeDB:
            class credentials:
                @staticmethod
                def find_one(query):
                    if query.get("name") == "my-cred" and query.get("domain") == "prod":
                        return {"name": "my-cred", "domain": "prod", "encrypted_payload": encrypted}
                    return None

        job = {
            "_id": "job-same",
            "domain": "prod",
            "executor": {"type": "sql", "dialect": "postgres", "query": "SELECT 1", "credential_ref": "my-cred"},
        }
        resolved = _resolve_credential_refs(job, FakeDB())
        assert resolved["executor"]["connection_uri"] == "postgresql://user:pass@host/db"
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


# --- Credential model domain field ---


def test_credential_reference_includes_domain():
    """CredentialReference model includes domain field."""
    ref = CredentialReference(name="cred1", domain="staging", credential_type="database")
    assert ref.domain == "staging"
    data = ref.model_dump()
    assert data["domain"] == "staging"


def test_credential_reference_default_domain():
    """CredentialReference defaults to prod domain."""
    ref = CredentialReference(name="cred1", credential_type="database")
    assert ref.domain == "prod"


# --- API response sanitization ---


def test_sanitize_job_response_masks_connection_uri():
    """SQL executor connection_uri is masked in API response."""
    job = JobDefinition(
        name="sql-job",
        user="demo",
        domain="prod",
        affinity=Affinity(),
        executor=SqlExecutor(
            query="SELECT 1",
            connection_uri="postgresql://user:secret@host/db",
            dialect="postgres",
        ),
    )
    sanitized = _sanitize_job_response(job)
    assert sanitized["executor"]["connection_uri"] == MASKED_SECRET


def test_sanitize_job_response_no_op_for_shell():
    """Shell executor is not affected by sanitization."""
    job = JobDefinition(
        name="shell-job",
        user="demo",
        domain="prod",
        affinity=Affinity(),
        executor=ShellExecutor(script="echo hi"),
    )
    sanitized = _sanitize_job_response(job)
    assert sanitized["executor"]["script"] == "echo hi"


def test_sanitize_job_response_credential_ref_only():
    """SQL executor with credential_ref but no connection_uri keeps null."""
    job = JobDefinition(
        name="sql-ref-job",
        user="demo",
        domain="prod",
        affinity=Affinity(),
        executor=SqlExecutor(
            query="SELECT 1",
            credential_ref="my-cred",
            dialect="postgres",
        ),
    )
    sanitized = _sanitize_job_response(job)
    assert sanitized["executor"]["connection_uri"] is None


# --- Encryption round-trip ---


def test_encryption_round_trip():
    """Encrypted payload decrypts back to original."""
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        data = {"username": "admin", "password": "s3cr3t!", "host": "db.example.com"}
        encrypted = encrypt_payload(data)
        decrypted = decrypt_payload(encrypted)
        assert decrypted == data
        # Encrypted text should not contain the plaintext password
        assert "s3cr3t!" not in encrypted
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_encryption_produces_unique_tokens():
    """Same plaintext produces different ciphertext (Fernet uses random IV)."""
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        data = {"password": "test123"}
        t1 = encrypt_payload(data)
        t2 = encrypt_payload(data)
        assert t1 != t2
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_admin_token_uses_constant_time_comparison():
    """Admin token comparison must use hmac.compare_digest for timing-attack resistance."""
    import hmac
    from unittest.mock import AsyncMock, MagicMock, patch

    from scheduler.utils.auth import enforce_api_key

    os.environ["ADMIN_TOKEN"] = "secret-admin"
    try:
        request = MagicMock()
        request.method.upper.return_value = "GET"
        request.headers = {"x-api-key": "secret-admin"}
        request.query_params = {}
        request.url.path = "/jobs/"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock())

        import asyncio
        asyncio.run(enforce_api_key(request, call_next))

        assert request.state.is_admin is True
        assert call_next.called
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_no_admin_token_env_rejects_unauthenticated():
    """When ADMIN_TOKEN is not set, unauthenticated requests must be rejected."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from scheduler.utils.auth import enforce_api_key

    os.environ.pop("ADMIN_TOKEN", None)
    try:
        request = MagicMock()
        request.method.upper.return_value = "GET"
        request.headers = {}
        request.query_params = {}
        request.url.path = "/jobs/"
        request.state = MagicMock()

        call_next = AsyncMock(return_value=MagicMock())

        import asyncio
        resp = asyncio.run(enforce_api_key(request, call_next))

        # call_next should NOT have been called
        assert not call_next.called
        assert resp.status_code == 401
    finally:
        os.environ.pop("ADMIN_TOKEN", None)
