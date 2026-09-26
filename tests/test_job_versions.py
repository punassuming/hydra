"""Tests for job definition versioning/audit trail (job_versions collection,
PUT /jobs/{id} recording a before/after snapshot, and the
GET /jobs/{id}/versions[/{version}] read endpoints).
"""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scheduler.main import app
from scheduler.utils.auth import _hash_token

_TEST_ADMIN_TOKEN = "test-admin-token-versions"
_TEST_DOMAIN_TOKEN = "test-domain-token-versions"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _admin_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}


def _job_doc(job_id="job-1", domain="prod", **overrides):
    now = datetime.now(timezone.utc)
    doc = {
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
    doc.update(overrides)
    return doc


class FakeJobDefinitions:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: d for d in (docs or [])}

    def find_one(self, query):
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, doc):
        self.docs[query["_id"]] = doc


class _SortableList(list):
    """Mimics enough of a pymongo cursor for .find(...).sort(field, direction)."""

    def sort(self, field, direction=-1):
        list.sort(self, key=lambda d: d.get(field), reverse=direction < 0)
        return self


class FakeJobVersions:
    def __init__(self):
        self.docs = []

    def count_documents(self, query):
        return len(self._match(query))

    def insert_one(self, doc):
        self.docs.append(doc)

    def find(self, query, _projection=None):
        return _SortableList(self._match(query))

    def find_one(self, query):
        matches = self._match(query)
        return matches[0] if matches else None

    def _match(self, query):
        return [doc for doc in self.docs if all(doc.get(k) == v for k, v in query.items())]


class FakeDB:
    def __init__(self, jobs=None):
        self.job_definitions = FakeJobDefinitions(jobs)
        self.job_versions = FakeJobVersions()


def test_update_job_records_a_version():
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        resp = client.put("/jobs/job-1", json={"timeout": 99}, headers=_admin_headers())
    assert resp.status_code == 200
    assert len(db.job_versions.docs) == 1
    version_doc = db.job_versions.docs[0]
    assert version_doc["version"] == 1
    assert version_doc["job_id"] == "job-1"
    assert version_doc["before"]["timeout"] == 30
    assert version_doc["after"]["timeout"] == 99


def test_update_job_increments_version_across_multiple_updates():
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        client.put("/jobs/job-1", json={"timeout": 50}, headers=_admin_headers())
        client.put("/jobs/job-1", json={"timeout": 60}, headers=_admin_headers())
    versions = sorted(v["version"] for v in db.job_versions.docs)
    assert versions == [1, 2]


def test_update_job_masks_secrets_in_version_snapshot():
    db = FakeDB([
        _job_doc(
            "job-sql", "prod",
            executor={"type": "sql", "dialect": "postgres", "query": "select 1", "connection_uri": "postgres://user:pw@host/db"},
        )
    ])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        resp = client.put("/jobs/job-sql", json={"timeout": 42}, headers=_admin_headers())
    assert resp.status_code == 200
    version_doc = db.job_versions.docs[0]
    assert version_doc["before"]["executor"]["connection_uri"] == "********"
    assert version_doc["after"]["executor"]["connection_uri"] != "postgres://user:pw@host/db"


def test_list_job_versions_returns_metadata_newest_first():
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        client.put("/jobs/job-1", json={"timeout": 50}, headers=_admin_headers())
        client.put("/jobs/job-1", json={"timeout": 60}, headers=_admin_headers())
        resp = client.get("/jobs/job-1/versions", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert [v["version"] for v in data] == [2, 1]
    assert "before" not in data[0]
    assert "after" not in data[0]


def test_get_job_version_returns_full_snapshot():
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        client.put("/jobs/job-1", json={"timeout": 77}, headers=_admin_headers())
        resp = client.get("/jobs/job-1/versions/1", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 1
    assert data["after"]["timeout"] == 77
    assert data["before"]["timeout"] == 30


def test_get_job_version_not_found():
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        resp = client.get("/jobs/job-1/versions/99", headers=_admin_headers())
    assert resp.status_code == 404


def test_job_versions_survive_job_deletion():
    """History stays visible even after the job definition itself is gone."""
    db = FakeDB([_job_doc("job-1", "prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        client.put("/jobs/job-1", json={"timeout": 88}, headers=_admin_headers())
        del db.job_definitions.docs["job-1"]
        resp = client.get("/jobs/job-1/versions/1", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["after"]["timeout"] == 88


def test_list_job_versions_cross_domain_forbidden_for_domain_token():
    db = FakeDB([_job_doc("job-beta", "beta")])
    auth_redis_alpha = _FakeAuthRedis(domain="alpha")
    with patch("scheduler.api.jobs.get_db", return_value=db):
        client.put("/jobs/job-beta", json={"timeout": 15}, headers=_admin_headers())
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.utils.auth.get_redis", return_value=auth_redis_alpha):
        resp = client.get(
            "/jobs/job-beta/versions",
            headers={"x-api-key": _TEST_DOMAIN_TOKEN, "x-domain": "alpha"},
        )
    assert resp.status_code == 200
    assert resp.json() == []


class _FakeAuthRedis:
    def __init__(self, domain: str):
        self.kv = {f"token_hash:{domain}": _hash_token(_TEST_DOMAIN_TOKEN)}

    def get(self, key):
        return self.kv.get(key)
