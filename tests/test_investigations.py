import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scheduler.main import app

_TEST_ADMIN_TOKEN = "test-admin-token-investigations"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _auth_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}


class _FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=-1):
        self.docs.sort(key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc), reverse=direction < 0)
        return self

    def limit(self, n):
        return self.docs[:n]

    def __iter__(self):
        return iter(self.docs)


def _matches(doc, query):
    for field, cond in query.items():
        value = doc.get(field)
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            if "$gte" in cond and (value is None or value < cond["$gte"]):
                return False
        elif value != cond:
            return False
    return True


class _FakeJobRuns:
    def __init__(self, runs):
        self._runs = runs

    def find(self, query, *_args, **_kwargs):
        return _FakeCursor([r for r in self._runs if _matches(r, query)])

    def count_documents(self, query):
        return len(list(self.find(query)))


class _FakeJobDefinitions:
    def __init__(self, jobs):
        self._jobs = jobs

    def find(self, query, *_args, **_kwargs):
        return list(self._jobs)


class _FakeDB:
    def __init__(self, jobs, runs):
        self.job_definitions = _FakeJobDefinitions(jobs)
        self.job_runs = _FakeJobRuns(runs)


def _now():
    return datetime.now(timezone.utc)


def test_list_investigations_returns_catalog():
    response = client.get("/investigations/", headers=_auth_headers())
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()}
    assert keys == {"failed_recent", "long_running_outliers", "flaky_jobs", "never_succeeded"}


def test_unknown_investigation_404():
    response = client.get("/investigations/does_not_exist", headers=_auth_headers())
    assert response.status_code == 404


def test_failed_recent_surfaces_jobs_with_recent_failures():
    jobs = [{"_id": "job-1", "name": "nightly-backup", "domain": "prod"}]
    runs = [
        {"_id": "r1", "job_id": "job-1", "status": "failed", "start_ts": _now() - timedelta(hours=1)},
        {"_id": "r2", "job_id": "job-1", "status": "failed", "start_ts": _now() - timedelta(hours=30)},  # outside window
    ]
    db = _FakeDB(jobs, runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/failed_recent", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-1"
    assert data["results"][0]["metric_value"] == 1


def test_long_running_outliers_flags_run_past_2x_p90():
    jobs = [{"_id": "job-1", "name": "etl", "domain": "prod"}]
    history = [
        {
            "_id": f"h{i}", "job_id": "job-1", "domain": "prod", "status": "success",
            "duration": 10.0, "start_ts": _now() - timedelta(days=i + 1),
        }
        for i in range(5)
    ]
    running = {
        "_id": "r-current", "job_id": "job-1", "domain": "prod",
        "status": "running", "start_ts": _now() - timedelta(seconds=30),
    }
    db = _FakeDB(jobs, history + [running])
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/long_running_outliers", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["last_run_id"] == "r-current"


def test_flaky_jobs_requires_mixed_outcomes():
    jobs = [
        {"_id": "job-flaky", "name": "flaky", "domain": "prod"},
        {"_id": "job-stable", "name": "stable", "domain": "prod"},
    ]
    flaky_runs = [
        {
            "_id": f"f{i}", "job_id": "job-flaky",
            "status": "failed" if i % 2 == 0 else "success",
            "start_ts": _now() - timedelta(hours=i),
        }
        for i in range(10)
    ]
    stable_runs = [
        {"_id": f"s{i}", "job_id": "job-stable", "status": "success", "start_ts": _now() - timedelta(hours=i)}
        for i in range(10)
    ]
    db = _FakeDB(jobs, flaky_runs + stable_runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/flaky_jobs", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-flaky"


def test_never_succeeded_requires_minimum_run_count():
    jobs = [
        {"_id": "job-broken", "name": "broken", "domain": "prod"},
        {"_id": "job-new", "name": "new", "domain": "prod"},
    ]
    runs = [
        {"_id": "b1", "job_id": "job-broken", "status": "failed", "start_ts": _now() - timedelta(hours=1)},
        {"_id": "b2", "job_id": "job-broken", "status": "failed", "start_ts": _now() - timedelta(hours=2)},
        {"_id": "b3", "job_id": "job-broken", "status": "timed_out", "start_ts": _now() - timedelta(hours=3)},
        # job-new only has 1 run so far — should not qualify (below NEVER_SUCCEEDED_MIN_RUNS).
        {"_id": "n1", "job_id": "job-new", "status": "failed", "start_ts": _now() - timedelta(hours=1)},
    ]
    db = _FakeDB(jobs, runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/never_succeeded", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-broken"
    assert data["results"][0]["metric_value"] == 3
