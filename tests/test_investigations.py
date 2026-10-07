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
            if "$gt" in cond and (value is None or value <= cond["$gt"]):
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
    assert keys == {
        "failed_recent", "long_running_outliers", "flaky_jobs", "never_succeeded", "sla_miss", "retry_storm",
        "dead_letter", "queue_starvation", "worker_offline", "schedule_overdue",
    }


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


def test_sla_miss_flags_running_and_completed_runs_over_budget():
    jobs = [
        {"_id": "job-slow", "name": "slow", "domain": "prod", "sla_max_duration_seconds": 60},
        {"_id": "job-no-sla", "name": "no-sla", "domain": "prod", "sla_max_duration_seconds": None},
    ]
    runs = [
        # Completed run that blew past the 60s SLA.
        {
            "_id": "r1", "job_id": "job-slow", "status": "success", "duration": 120.0,
            "start_ts": _now() - timedelta(hours=1),
        },
        # Currently-running run already past the SLA.
        {
            "_id": "r2", "job_id": "job-slow", "status": "running",
            "start_ts": _now() - timedelta(seconds=90),
        },
        # Job with no SLA configured should never be flagged, even if slow.
        {
            "_id": "r3", "job_id": "job-no-sla", "status": "success", "duration": 999.0,
            "start_ts": _now() - timedelta(hours=1),
        },
    ]
    db = _FakeDB(jobs, runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/sla_miss", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-slow"
    assert data["results"][0]["metric_value"] == 60.0  # 120s duration - 60s SLA


def test_retry_storm_requires_minimum_retried_run_count():
    jobs = [
        {"_id": "job-storm", "name": "storm", "domain": "prod"},
        {"_id": "job-quiet", "name": "quiet", "domain": "prod"},
    ]
    runs = [
        {
            "_id": f"s{i}", "job_id": "job-storm", "status": "failed", "retry_attempt": i + 1,
            "start_ts": _now() - timedelta(hours=i),
        }
        for i in range(3)
    ]
    # Only 2 retried runs — below RETRY_STORM_MIN_COUNT (3), should not qualify.
    runs += [
        {
            "_id": f"q{i}", "job_id": "job-quiet", "status": "failed", "retry_attempt": i + 1,
            "start_ts": _now() - timedelta(hours=i),
        }
        for i in range(2)
    ]
    db = _FakeDB(jobs, runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/retry_storm", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-storm"
    assert data["results"][0]["metric_value"] == 3


def test_dead_letter_requires_exhausted_retries_on_latest_run():
    jobs = [
        # Exhausted all 2 configured retries, latest run still failed.
        {"_id": "job-exhausted", "name": "exhausted", "domain": "prod", "max_retries": 2},
        # Still has retries left (retry_attempt 1 of 2) — not exhausted yet.
        {"_id": "job-retrying", "name": "retrying", "domain": "prod", "max_retries": 2},
        # No retry policy configured at all — never counts as "exhausted".
        {"_id": "job-no-retries", "name": "no-retries", "domain": "prod", "max_retries": 0},
        # Exhausted retries, but the latest run actually succeeded.
        {"_id": "job-recovered", "name": "recovered", "domain": "prod", "max_retries": 2},
    ]
    runs = [
        {
            "_id": "e1", "job_id": "job-exhausted", "status": "failed", "retry_attempt": 2,
            "start_ts": _now() - timedelta(hours=1),
        },
        {
            "_id": "r1", "job_id": "job-retrying", "status": "failed", "retry_attempt": 1,
            "start_ts": _now() - timedelta(hours=1),
        },
        {
            "_id": "n1", "job_id": "job-no-retries", "status": "failed", "retry_attempt": 0,
            "start_ts": _now() - timedelta(hours=1),
        },
        {
            "_id": "c1", "job_id": "job-recovered", "status": "success", "retry_attempt": 2,
            "start_ts": _now() - timedelta(hours=1),
        },
    ]
    db = _FakeDB(jobs, runs)
    with patch("scheduler.api.investigations.get_db", return_value=db):
        response = client.get("/investigations/dead_letter", headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["job_id"] == "job-exhausted"
    assert data["results"][0]["metric_value"] == 2


class _FakeRedis:
    """Just the Redis calls the Redis-backed investigations make."""

    def __init__(self, pending=None, meta=None, workers=None, heartbeats=None):
        self._pending = pending or {}  # domain -> [job_id]
        self._meta = meta or {}  # "domain:job_id" -> dict
        self._workers = workers or {}  # "workers:domain:wid" -> dict
        self._heartbeats = heartbeats or {}  # (domain, wid) -> ts

    def zrange(self, key, start, end):
        return list(self._pending.get(key.split(":")[1], []))

    def hgetall(self, key):
        if key.startswith("job_enqueue_meta:"):
            return self._meta.get(key.split(":", 1)[1], {})
        return self._workers.get(key, {})

    def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        return iter([k for k in self._workers if k.startswith(prefix)])

    def zscore(self, key, member):
        return self._heartbeats.get((key.split(":", 1)[1], member))


def test_queue_starvation_flags_pending_jobs_at_threshold():
    jobs = [
        {"_id": "stuck", "name": "needs-gpu", "domain": "prod"},
        {"_id": "ok", "name": "fine", "domain": "prod"},
        {"_id": "not-pending", "name": "old-meta", "domain": "prod"},
    ]
    r = _FakeRedis(
        pending={"prod": ["stuck", "ok"]},
        meta={
            "prod:stuck": {"no_worker_count": "9", "enqueued_ts": str(_now().timestamp())},
            "prod:ok": {"no_worker_count": "1"},
            "prod:not-pending": {"no_worker_count": "50"},  # stale meta, not in the pending queue
        },
    )
    with patch("scheduler.api.investigations.get_db", return_value=_FakeDB(jobs, [])), patch(
        "scheduler.api.investigations.get_redis", return_value=r
    ):
        response = client.get("/investigations/queue_starvation", headers=_auth_headers())
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["job_id"] for row in rows] == ["stuck"]
    assert rows[0]["metric_value"] == 9
    assert rows[0]["last_run_at"] is not None


def test_worker_offline_flags_stale_heartbeats_but_not_deliberate_offline():
    now = _now().timestamp()
    r = _FakeRedis(
        workers={
            "workers:prod:dead": {"state": "online", "hostname": "box-1"},
            "workers:prod:healthy": {"state": "online"},
            "workers:prod:parked": {"state": "offline"},  # operator set it offline
            "workers:prod:unknown": {"state": "online"},  # no heartbeat on record
        },
        heartbeats={
            ("prod", "dead"): now - 120,
            ("prod", "healthy"): now - 1,
            ("prod", "parked"): now - 9999,
        },
    )
    with patch("scheduler.api.investigations.get_db", return_value=_FakeDB([], [])), patch(
        "scheduler.api.investigations.get_redis", return_value=r
    ):
        response = client.get("/investigations/worker_offline?domain=prod", headers=_auth_headers())
    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["job_id"] for row in rows] == ["dead"]
    assert rows[0]["entity"] == "worker"
    assert rows[0]["job_name"] == "box-1"
    assert rows[0]["metric_value"] >= 120


def test_schedule_overdue_flags_only_stale_enabled_cron_and_interval_jobs():
    now = _now()
    stale = now - timedelta(minutes=30)
    jobs = [
        {"_id": "overdue", "name": "stuck-cron", "domain": "prod",
         "schedule": {"mode": "cron", "enabled": True, "next_run_at": stale}},
        {"_id": "iso-string", "name": "iso", "domain": "prod",
         "schedule": {"mode": "interval", "enabled": True, "next_run_at": stale.isoformat()}},
        {"_id": "on-time", "name": "fine", "domain": "prod",
         "schedule": {"mode": "cron", "enabled": True, "next_run_at": now + timedelta(minutes=5)}},
        {"_id": "just-late", "name": "within-grace", "domain": "prod",
         "schedule": {"mode": "cron", "enabled": True, "next_run_at": now - timedelta(seconds=30)}},
        {"_id": "disabled", "name": "paused", "domain": "prod",
         "schedule": {"mode": "cron", "enabled": False, "next_run_at": stale}},
        {"_id": "immediate", "name": "one-shot", "domain": "prod",
         "schedule": {"mode": "immediate", "enabled": True, "next_run_at": stale}},
        {"_id": "ended", "name": "window-closed", "domain": "prod",
         "schedule": {"mode": "cron", "enabled": True, "next_run_at": stale, "end_at": now - timedelta(days=1)}},
        {"_id": "no-schedule", "name": "bare", "domain": "prod"},
    ]
    with patch("scheduler.api.investigations.get_db", return_value=_FakeDB(jobs, [])):
        response = client.get("/investigations/schedule_overdue", headers=_auth_headers())
    assert response.status_code == 200
    assert {row["job_id"] for row in response.json()["results"]} == {"overdue", "iso-string"}
    assert all(row["metric_value"] >= 29 for row in response.json()["results"])
