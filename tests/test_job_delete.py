"""Tests for the DELETE /jobs/{job_id} endpoint."""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scheduler.main import app
from scheduler.utils.auth import _hash_token

_TEST_ADMIN_TOKEN = "test-admin-token-delete"
_TEST_DOMAIN_TOKEN = "test-domain-token-delete"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _admin_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}


def _job_doc(job_id="job-1", domain="prod"):
    now = datetime.now(timezone.utc)
    return {
        "_id": job_id,
        "name": "test-job",
        "user": "tester",
        "domain": domain,
        "priority": 5,
        "affinity": {"os": [], "tags": [], "allowed_users": []},
        "executor": {"type": "shell", "script": "echo hi"},
        "retries": 0,
        "timeout": 30,
        "schedule": {"mode": "immediate", "enabled": True},
        "completion": {},
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: d for d in (docs or [])}
        self.deleted_ids = []

    def find_one(self, query):
        return self.docs.get(query.get("_id"))

    def delete_one(self, query):
        job_id = query.get("_id")
        self.deleted_ids.append(job_id)
        self.docs.pop(job_id, None)


class FakeDB:
    def __init__(self, jobs=None):
        self.job_definitions = FakeCollection(jobs)


class FakeRedis:
    def __init__(self):
        self.zrem_calls = []
        self.deleted_keys = []
        self.kv = {}

    def zrem(self, key, member):
        self.zrem_calls.append((key, member))

    def delete(self, key):
        self.deleted_keys.append(key)

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value):
        self.kv[key] = value


def test_delete_job_removes_definition_and_queue_entries():
    db = FakeDB([_job_doc("job-1", "prod")])
    r = FakeRedis()
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs.get_redis", return_value=r):
        resp = client.delete("/jobs/job-1", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1", "deleted": True}
    assert db.job_definitions.deleted_ids == ["job-1"]
    assert ("job_queue:prod:pending", "job-1") in r.zrem_calls
    assert "job_enqueue_meta:prod:job-1" in r.deleted_keys


def test_delete_job_not_found():
    db = FakeDB([])
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs.get_redis", return_value=FakeRedis()):
        resp = client.delete("/jobs/missing", headers=_admin_headers())
    assert resp.status_code == 404


def test_delete_job_cross_domain_forbidden():
    """A domain token for 'alpha' cannot delete a job that lives in 'beta'."""
    db = FakeDB([_job_doc("job-beta", "beta")])
    auth_redis = FakeRedis()
    auth_redis.kv["token_hash:alpha"] = _hash_token(_TEST_DOMAIN_TOKEN)
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs.get_redis", return_value=FakeRedis()), \
         patch("scheduler.utils.auth.get_redis", return_value=auth_redis):
        resp = client.delete(
            "/jobs/job-beta",
            headers={"x-api-key": _TEST_DOMAIN_TOKEN, "x-domain": "alpha"},
        )
    assert resp.status_code == 403
    # Nothing was deleted
    assert db.job_definitions.deleted_ids == []
    assert "job-beta" in db.job_definitions.docs


def test_delete_job_same_domain_allowed():
    db = FakeDB([_job_doc("job-alpha", "alpha")])
    r = FakeRedis()
    auth_redis = FakeRedis()
    auth_redis.kv["token_hash:alpha"] = _hash_token(_TEST_DOMAIN_TOKEN)
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs.get_redis", return_value=r), \
         patch("scheduler.utils.auth.get_redis", return_value=auth_redis):
        resp = client.delete(
            "/jobs/job-alpha",
            headers={"x-api-key": _TEST_DOMAIN_TOKEN, "x-domain": "alpha"},
        )
    assert resp.status_code == 200
    assert db.job_definitions.deleted_ids == ["job-alpha"]
    assert ("job_queue:alpha:pending", "job-alpha") in r.zrem_calls
