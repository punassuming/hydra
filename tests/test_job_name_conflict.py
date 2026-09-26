"""Tests that a duplicate (domain, name) job definition surfaces as a clean
409, not an unhandled DuplicateKeyError/500 — the unique index on
job_definitions (scheduler/startup.py) enforces uniqueness at the DB layer,
but only the template-import endpoint used to check for the conflict itself
before this fix; submit_job/update_job/run_adhoc_job relied on nothing
catching it.
"""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from scheduler.main import app

_TEST_ADMIN_TOKEN = "test-admin-token-name-conflict"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _admin_headers():
    # ADMIN_DOMAIN defaults to "admin", not "prod" — pin x-domain explicitly
    # so the admin-token requests below land in the same domain as the
    # fixture jobs (domain="prod"), or the (domain, name) conflict this
    # test suite exists to check for would never actually trigger.
    return {"x-api-key": _TEST_ADMIN_TOKEN, "x-domain": "prod"}


def _job_doc(job_id="job-1", name="test-job", domain="prod"):
    now = datetime.now(timezone.utc)
    return {
        "_id": job_id,
        "name": name,
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


class FakeJobDefinitions:
    """Mimics MongoDB's unique (domain, name) index behavior: insert_one/
    replace_one raise DuplicateKeyError when the write would create a second
    document with the same (domain, name) pair."""

    def __init__(self, docs=None):
        self.docs = {d["_id"]: d for d in (docs or [])}

    def find_one(self, query):
        return self.docs.get(query.get("_id"))

    def _conflicts(self, doc, exclude_id=None):
        return any(
            other["domain"] == doc["domain"] and other["name"] == doc["name"] and _id != exclude_id
            for _id, other in self.docs.items()
        )

    def insert_one(self, doc):
        if self._conflicts(doc):
            raise DuplicateKeyError("E11000 duplicate key error collection: job_definitions")
        self.docs[doc["_id"]] = doc

    def replace_one(self, query, doc):
        job_id = query["_id"]
        if self._conflicts(doc, exclude_id=job_id):
            raise DuplicateKeyError("E11000 duplicate key error collection: job_definitions")
        self.docs[job_id] = doc


class FakeJobVersions:
    def __init__(self):
        self.docs = []

    def count_documents(self, _query):
        return len(self.docs)

    def insert_one(self, doc):
        self.docs.append(doc)


class FakeDB:
    def __init__(self, jobs=None):
        self.job_definitions = FakeJobDefinitions(jobs)
        self.job_versions = FakeJobVersions()


def test_submit_job_duplicate_name_returns_409_not_500():
    db = FakeDB([_job_doc("job-1", name="nightly-backup", domain="prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs._enqueue_job"):
        resp = client.post(
            "/jobs/",
            json={
                "name": "nightly-backup",
                "user": "tester",
                "executor": {"type": "shell", "script": "echo hi"},
            },
            headers=_admin_headers(),
        )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_submit_job_unique_name_succeeds():
    db = FakeDB([_job_doc("job-1", name="nightly-backup", domain="prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs._enqueue_job"):
        resp = client.post(
            "/jobs/",
            json={
                "name": "a-different-name",
                "user": "tester",
                "executor": {"type": "shell", "script": "echo hi"},
            },
            headers=_admin_headers(),
        )
    assert resp.status_code == 200


def test_update_job_rename_to_existing_name_returns_409_and_records_no_version():
    db = FakeDB([
        _job_doc("job-1", name="job-one", domain="prod"),
        _job_doc("job-2", name="job-two", domain="prod"),
    ])
    with patch("scheduler.api.jobs.get_db", return_value=db):
        resp = client.put("/jobs/job-2", json={"name": "job-one"}, headers=_admin_headers())
    assert resp.status_code == 409
    # The failed rename must not leave a phantom job_versions entry behind.
    assert db.job_versions.docs == []


def test_run_adhoc_job_duplicate_name_returns_409_not_500():
    db = FakeDB([_job_doc("job-1", name="existing-adhoc", domain="prod")])
    with patch("scheduler.api.jobs.get_db", return_value=db), \
         patch("scheduler.api.jobs._enqueue_job"):
        resp = client.post(
            "/jobs/adhoc",
            json={
                "name": "existing-adhoc",
                "user": "tester",
                "executor": {"type": "shell", "script": "echo hi"},
            },
            headers=_admin_headers(),
        )
    assert resp.status_code == 409
