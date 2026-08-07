"""Multi-domain isolation: a domain token must never see another domain's
jobs, runs, or workers — only the API-level guarantee, not the UI hiding it."""

import pytest

from ._client import ApiError
from ._config import SKIP_REASON, enabled

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


def test_two_fresh_domains_are_isolated(domain_factory, admin_client):
    domain_a = domain_factory()
    domain_b = domain_factory()

    job = domain_a.client.post(
        "/jobs/",
        {
            "name": "isolation-check",
            "executor": {"type": "shell", "shell": "bash", "script": "true"},
            "schedule": {"mode": "cron", "cron": "0 0 1 1 *", "enabled": False},  # never actually runs
        },
    )
    job_id = job.get("_id") or job.get("id")
    assert job_id

    # Domain B must not be able to fetch domain A's job directly.
    with pytest.raises(ApiError) as exc_info:
        domain_b.client.get(f"/jobs/{job_id}")
    assert exc_info.value.status == 403

    # Domain B's job list must not include it either.
    b_jobs = domain_b.client.get("/jobs/")
    assert not any((j.get("_id") or j.get("id")) == job_id for j in b_jobs)

    # Domain A can see its own job.
    own = domain_a.client.get(f"/jobs/{job_id}")
    assert (own.get("_id") or own.get("id")) == job_id

    # Admin can see it via either domain-scoped or cross-domain listing.
    admin_view = admin_client.get(f"/jobs/{job_id}")
    assert (admin_view.get("_id") or admin_view.get("id")) == job_id


def test_domain_b_cannot_use_domain_a_worker_visibility(domain_factory):
    domain_a = domain_factory(with_worker=(True))
    domain_b = domain_factory()

    a_workers = domain_a.client.get("/workers/")
    assert any(w.get("domain") == domain_a.name for w in a_workers), "domain A should see its own worker"

    b_workers = domain_b.client.get("/workers/")
    assert not any(w.get("domain") == domain_a.name for w in b_workers), (
        "domain B must not see domain A's worker"
    )


def test_credentials_are_domain_scoped(domain_factory):
    domain_a = domain_factory()
    domain_b = domain_factory()

    domain_a.client.post("/credentials/", {"name": "isolation-cred", "credential_type": "generic", "extra": {"k": "v"}})

    a_creds = domain_a.client.get("/credentials/")["credentials"]
    assert any(c["name"] == "isolation-cred" for c in a_creds)

    b_creds = domain_b.client.get("/credentials/")["credentials"]
    assert not any(c["name"] == "isolation-cred" for c in b_creds)
