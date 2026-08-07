"""Credential store: secrets are write-only (never echoed back) and
domain-scoped CRUD works end to end.

Whether CREDENTIAL_ENCRYPTION_KEY is explicitly set (as opposed to derived
from ADMIN_TOKEN — see scheduler/startup.py::warn_credential_encryption_key)
is NOT checked here: it isn't observable via the API by design (that would
be an information leak), and actually testing the failure mode would mean
rotating your real ADMIN_TOKEN, which is too destructive for an automated
suite to do to a live deployment. Check the scheduler's startup logs for
that warning manually instead — see tests/acceptance/README.md.
"""

import pytest

from ._client import ApiError
from ._config import SKIP_REASON, enabled

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


def test_credential_secrets_are_never_returned(domain_factory):
    domain = domain_factory()
    domain.client.post(
        "/credentials/",
        {
            "name": "acceptance-db",
            "credential_type": "database",
            "dialect": "postgres",
            "connection_uri": "postgresql://acceptance_user:super-secret-password@db.internal:5432/app",
        },
    )

    creds = domain.client.get("/credentials/")["credentials"]
    match = next(c for c in creds if c["name"] == "acceptance-db")
    serialized = str(match)
    assert "super-secret-password" not in serialized
    assert "connection_uri" not in match
    assert "encrypted_payload" not in match


def test_credential_update_and_delete(domain_factory):
    domain = domain_factory()
    domain.client.post(
        "/credentials/", {"name": "acceptance-rotatable", "credential_type": "generic", "extra": {"v": 1}}
    )
    domain.client.put(
        "/credentials/acceptance-rotatable",
        {"name": "acceptance-rotatable", "credential_type": "generic", "extra": {"v": 2}},
    )

    creds = domain.client.get("/credentials/")["credentials"]
    assert any(c["name"] == "acceptance-rotatable" for c in creds)

    domain.client.delete("/credentials/acceptance-rotatable")
    creds_after = domain.client.get("/credentials/")["credentials"]
    assert not any(c["name"] == "acceptance-rotatable" for c in creds_after)


def test_duplicate_credential_name_rejected(domain_factory):
    domain = domain_factory()
    domain.client.post("/credentials/", {"name": "acceptance-dup", "credential_type": "generic"})
    with pytest.raises(ApiError) as exc_info:
        domain.client.post("/credentials/", {"name": "acceptance-dup", "credential_type": "generic"})
    assert exc_info.value.status == 409
