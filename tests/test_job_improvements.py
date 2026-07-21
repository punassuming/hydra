"""Test the new job management improvements"""
from scheduler.api.jobs import _validate_job_definition
from scheduler.models.executor import (
    ExternalExecutor,
    PowerShellExecutor,
    ShellExecutor,
    SqlExecutor,
)
from scheduler.models.job_definition import Affinity, JobDefinition
from scheduler.utils.affinity import executor_types_match, passes_affinity
from scheduler.utils.encryption import decrypt_payload, encrypt_payload
from worker.executor import _detect_capabilities, _detect_shells


def test_job_definition_with_tags():
    """Test that job definitions can include tags"""
    job = JobDefinition(
        name="test-job",
        user="testuser",
        affinity=Affinity(),
        executor=ShellExecutor(script="echo hello"),
        tags=["production", "critical", "data-processing"]
    )
    
    assert job.tags == ["production", "critical", "data-processing"]
    result = _validate_job_definition(job)
    assert result.valid


def test_job_definition_with_empty_tags():
    """Test that job definitions work with empty tags"""
    job = JobDefinition(
        name="test-job",
        user="testuser",
        affinity=Affinity(),
        executor=ShellExecutor(script="echo hello"),
        tags=[]
    )
    
    assert job.tags == []
    result = _validate_job_definition(job)
    assert result.valid


def test_job_definition_default_tags():
    """Test that tags default to empty list"""
    job = JobDefinition(
        name="test-job",
        user="testuser",
        affinity=Affinity(),
        executor=ShellExecutor(script="echo hello")
    )
    
    assert job.tags == []
    result = _validate_job_definition(job)
    assert result.valid


# --- PowerShell executor tests ---


def test_validate_powershell_executor():
    job = JobDefinition(
        name="ps-job",
        user="a",
        affinity=Affinity(),
        executor=PowerShellExecutor(script="Write-Host 'hello'"),
    )
    result = _validate_job_definition(job)
    assert result.valid


def test_validate_powershell_empty_script_fails():
    job = JobDefinition(
        name="ps-bad",
        user="a",
        affinity=Affinity(),
        executor=PowerShellExecutor(script="  "),
    )
    result = _validate_job_definition(job)
    assert not result.valid
    assert any("powershell" in e for e in result.errors)


# --- SQL executor tests ---


def test_validate_sql_executor():
    job = JobDefinition(
        name="sql-job",
        user="a",
        affinity=Affinity(),
        executor=SqlExecutor(query="SELECT 1;", connection_uri="postgresql://localhost/db"),
    )
    result = _validate_job_definition(job)
    assert result.valid


def test_validate_sql_executor_mongodb():
    job = JobDefinition(
        name="sql-mongo",
        user="a",
        affinity=Affinity(),
        executor=SqlExecutor(dialect="mongodb", query="ping", connection_uri="mongodb://localhost"),
    )
    result = _validate_job_definition(job)
    assert result.valid


def test_validate_sql_no_query_fails():
    job = JobDefinition(
        name="sql-bad",
        user="a",
        affinity=Affinity(),
        executor=SqlExecutor(query="", connection_uri="postgresql://localhost/db"),
    )
    result = _validate_job_definition(job)
    assert not result.valid


def test_validate_sql_no_connection_fails():
    job = JobDefinition(
        name="sql-bad",
        user="a",
        affinity=Affinity(),
        executor=SqlExecutor(query="SELECT 1;"),
    )
    result = _validate_job_definition(job)
    assert not result.valid


def test_validate_sql_credential_ref_is_sufficient():
    job = JobDefinition(
        name="sql-ref",
        user="a",
        affinity=Affinity(),
        executor=SqlExecutor(query="SELECT 1;", credential_ref="my-cred"),
    )
    result = _validate_job_definition(job)
    assert result.valid


# --- Affinity executor_types tests ---


def test_affinity_executor_types_field():
    affinity = Affinity(executor_types=["python", "sql"])
    assert affinity.executor_types == ["python", "sql"]


def test_executor_types_match_empty_passes():
    assert executor_types_match([], ["shell", "python"])


def test_executor_types_match_subset():
    assert executor_types_match(["python"], ["shell", "python", "sql"])


def test_executor_types_match_fails():
    assert not executor_types_match(["powershell"], ["shell", "python"])


def test_passes_affinity_with_executor_types():
    job = {
        "user": "alice",
        "affinity": {
            "os": ["linux"],
            "tags": [],
            "allowed_users": [],
            "executor_types": ["python", "sql"],
        },
    }
    worker_ok = {
        "os": "linux",
        "tags": [],
        "allowed_users": [],
        "capabilities": ["shell", "python", "sql", "external"],
        "max_concurrency": 2,
        "current_running": 0,
    }
    worker_missing_sql = {
        "os": "linux",
        "tags": [],
        "allowed_users": [],
        "capabilities": ["shell", "python"],
        "max_concurrency": 2,
        "current_running": 0,
    }
    assert passes_affinity(job, worker_ok)
    assert not passes_affinity(job, worker_missing_sql)


# --- Worker capability detection ---


def test_detect_shells():
    shells = _detect_shells()
    assert isinstance(shells, list)
    # bash should be detected on Linux CI
    assert "bash" in shells


def test_detect_capabilities():
    caps = _detect_capabilities()
    assert isinstance(caps, list)
    assert "shell" in caps
    assert "external" in caps
    assert "python" in caps


# --- Encryption tests ---


def test_encrypt_decrypt_roundtrip():
    import os
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        data = {"connection_uri": "postgresql://user:pass@host/db", "password": "s3cret"}
        token = encrypt_payload(data)
        assert isinstance(token, str)
        decrypted = decrypt_payload(token)
        assert decrypted == data
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_encrypt_produces_different_tokens():
    import os
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        data = {"key": "value"}
        t1 = encrypt_payload(data)
        t2 = encrypt_payload(data)
        # Fernet includes timestamp and initialization vector (IV), so tokens differ even for same input
        assert t1 != t2
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


# --- Credential resolution at dispatch tests ---


def test_resolve_credential_refs_with_connection_uri():
    """credential_ref is resolved to connection_uri from encrypted payload."""
    import os

    from scheduler.scheduler import _resolve_credential_refs
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        encrypted = encrypt_payload({"connection_uri": "postgresql://user:pass@host/db"})

        class FakeDB:
            class credentials:
                @staticmethod
                def find_one(query):
                    if query.get("name") == "prod-db" and query.get("domain") == "prod":
                        return {"name": "prod-db", "domain": "prod", "encrypted_payload": encrypted}
                    return None

        job = {
            "_id": "job1",
            "domain": "prod",
            "executor": {"type": "sql", "dialect": "postgres", "query": "SELECT 1", "credential_ref": "prod-db"},
        }
        resolved = _resolve_credential_refs(job, FakeDB())
        assert resolved["executor"]["connection_uri"] == "postgresql://user:pass@host/db"
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_resolve_credential_refs_from_discrete_fields():
    """credential_ref with host/user/password fields constructs a connection_uri."""
    import os

    from scheduler.scheduler import _resolve_credential_refs
    os.environ["ADMIN_TOKEN"] = "test-admin-token"
    try:
        encrypted = encrypt_payload({
            "username": "admin",
            "password": "secret",
            "host": "db.example.com",
            "port": 5432,
            "database": "mydb",
        })

        class FakeDB:
            class credentials:
                @staticmethod
                def find_one(query):
                    if query.get("name") == "prod-db" and query.get("domain") == "prod":
                        return {"name": "prod-db", "domain": "prod", "encrypted_payload": encrypted}
                    return None

        job = {
            "_id": "job2",
            "domain": "prod",
            "executor": {"type": "sql", "dialect": "postgres", "query": "SELECT 1", "credential_ref": "prod-db"},
        }
        resolved = _resolve_credential_refs(job, FakeDB())
        assert "postgresql://admin:secret@db.example.com:5432/mydb" == resolved["executor"]["connection_uri"]
    finally:
        os.environ.pop("ADMIN_TOKEN", None)


def test_resolve_credential_refs_skips_non_sql():
    """Non-SQL executors are returned unchanged."""
    from scheduler.scheduler import _resolve_credential_refs
    job = {"_id": "job3", "executor": {"type": "shell", "script": "echo hi"}}
    assert _resolve_credential_refs(job, None) is job


def test_resolve_credential_refs_skips_inline_uri():
    """Jobs with inline connection_uri are not overwritten."""
    from scheduler.scheduler import _resolve_credential_refs
    job = {
        "_id": "job4",
        "executor": {
            "type": "sql",
            "query": "SELECT 1",
            "connection_uri": "existing://uri",
            "credential_ref": "cred",
        },
    }
    resolved = _resolve_credential_refs(job, None)
    assert resolved["executor"]["connection_uri"] == "existing://uri"


# ── retry_count convenience field ────────────────────────────────────


def test_retry_count_maps_to_max_retries():
    """retry_count on JobCreate should map to max_retries when max_retries is 0."""
    from scheduler.api.jobs import _apply_retry_count
    from scheduler.models.job_definition import JobCreate

    job = JobCreate(
        name="retry-test",
        executor=ShellExecutor(script="echo hi"),
        retry_count=3,
    )
    payload = _apply_retry_count(job.model_dump())
    assert payload["max_retries"] == 3
    assert "retry_count" not in payload


def test_retry_count_does_not_override_explicit_max_retries():
    """If max_retries is explicitly set, retry_count should not override it."""
    from scheduler.api.jobs import _apply_retry_count
    from scheduler.models.job_definition import JobCreate

    job = JobCreate(
        name="retry-test",
        executor=ShellExecutor(script="echo hi"),
        retry_count=5,
        max_retries=2,
    )
    payload = _apply_retry_count(job.model_dump())
    assert payload["max_retries"] == 2
    assert "retry_count" not in payload


def test_retry_count_none_leaves_max_retries_unchanged():
    """When retry_count is None, max_retries defaults should be preserved."""
    from scheduler.api.jobs import _apply_retry_count
    from scheduler.models.job_definition import JobCreate

    job = JobCreate(
        name="no-retry",
        executor=ShellExecutor(script="echo hi"),
    )
    payload = _apply_retry_count(job.model_dump())
    assert payload["max_retries"] == 0
    assert "retry_count" not in payload


def test_job_create_domain_deprecated():
    """JobCreate still accepts domain but it should be deprecated."""
    from scheduler.models.job_definition import JobCreate

    job = JobCreate(
        name="domain-test",
        executor=ShellExecutor(script="echo hi"),
        domain="staging",
    )
    # Field accepted but the API overwrites it -- just verify the model works.
    assert job.domain == "staging"
