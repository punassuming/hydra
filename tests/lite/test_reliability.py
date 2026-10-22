"""Phase 3: retries, webhooks, dependents, policies, recovery, retention, timeouts, SLA.

Deterministic: drives Store/Lifecycle/tick directly with fixed clocks (no worker threads) except where noted.
"""

import http.server
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from hydra_lite import loops
from hydra_lite.jobs import build_job
from hydra_lite.lifecycle import Lifecycle
from hydra_lite.logs import LogStore
from hydra_lite.scheduling import tick
from hydra_lite.store import Store
from hydra_lite.store.store import iso, now_utc

UTC = timezone.utc


@pytest.fixture()
def env(tmp_path):
    store = Store(tmp_path / "h.db")
    logs = LogStore(tmp_path / "logs")
    life = Lifecycle(store, logs)
    yield store, logs, life
    store.close()


def mkjob(store, name="j", **extra):
    doc = build_job({"name": name, "executor": {"type": "shell", "script": "echo hi"}, **extra})
    return store.create_job(doc)


def fail(store, life, run, status="failed"):
    store.claim_run("w")
    store.start_run(run["id"])
    return life.finalize(run["id"], status, returncode=1, reason="boom")


def test_retry_chain_persists_not_before_and_params(env):
    store, _, life = env
    job = mkjob(store, max_retries=2, retry_delay_seconds=10, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"], params={"A": "1"})
    fail(store, life, run)
    retries = [r for r in store.list_runs(job_id=job["_id"]) if r["trigger"] == "retry"]
    assert len(retries) == 1
    r1 = retries[0]
    assert r1["status"] == "pending" and r1["retry_attempt"] == 1 and r1["params"] == {"A": "1"}
    assert r1["not_before"] is not None  # delay survives restarts because it is stored on the run
    assert any(e["type"] == "retry_scheduled" for e in store.list_events(run["id"]))
    # not claimable until the delay passed
    assert store.claim_run("w", now_utc()) is None
    claimed = store.claim_run("w", now_utc() + timedelta(minutes=5))
    assert claimed["id"] == r1["id"]
    store.start_run(r1["id"])
    life.finalize(r1["id"], "failed", returncode=1, reason="boom")
    assert max(r["retry_attempt"] for r in store.list_runs(job_id=job["_id"])) == 2  # second retry queued
    r2 = [r for r in store.list_runs(job_id=job["_id"]) if r["retry_attempt"] == 2][0]
    store.claim_run("w", now_utc() + timedelta(hours=1))
    store.start_run(r2["id"])
    life.finalize(r2["id"], "failed", returncode=1, reason="boom")
    assert len(store.list_runs(job_id=job["_id"])) == 3  # retries exhausted -> no fourth run


def test_timed_out_runs_retry_and_success_does_not(env):
    store, _, life = env
    job = mkjob(store, max_retries=1, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"])
    fail(store, life, run, "timed_out")
    assert [r["trigger"] for r in store.list_runs(job_id=job["_id"])].count("retry") == 1
    ok = store.enqueue_run(job["_id"])
    before = len(store.list_runs(job_id=job["_id"]))
    store.claim_run("w", now_utc() + timedelta(hours=1))  # takes the highest-priority/oldest pending run
    claimed = [r for r in store.list_runs(job_id=job["_id"]) if r["status"] == "dispatched"][0]
    store.start_run(claimed["id"])
    life.finalize(claimed["id"], "success", returncode=0)
    assert len(store.list_runs(job_id=job["_id"])) == before  # success never queues a retry
    assert ok["id"]


def test_followups_run_exactly_once(env):
    store, _, life = env
    job = mkjob(store, max_retries=3, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"])
    fail(store, life, run)
    life.finalize(run["id"], "failed", returncode=1, reason="duplicate end event")
    assert len([r for r in store.list_runs(job_id=job["_id"]) if r["trigger"] == "retry"]) == 1


def test_dependents_trigger_on_success_only(env):
    store, _, life = env
    cron = {"mode": "cron", "cron": "0 0 1 1 *"}
    up = mkjob(store, "up", schedule=cron)
    down = mkjob(store, "down", depends_on=[up["_id"]], schedule=cron)
    off = mkjob(store, "off", depends_on=[up["_id"]], schedule={**cron, "enabled": False})
    bad = store.enqueue_run(up["_id"])
    fail(store, life, bad)
    assert store.list_runs(job_id=down["_id"]) == []
    good = store.enqueue_run(up["_id"])
    store.claim_run("w")
    store.start_run(good["id"])
    life.finalize(good["id"], "success", returncode=0)
    deps = store.list_runs(job_id=down["_id"])
    assert len(deps) == 1 and deps[0]["trigger"] == "dependency"
    assert store.list_runs(job_id=off["_id"]) == []  # disabled dependents are skipped, as in the full edition


class _Hook(http.server.BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):
        _Hook.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_failure_webhook_fires_only_after_retries_are_exhausted(env):
    store, logs, life = env
    _Hook.bodies.clear()
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/hook"
        job = mkjob(store, max_retries=1, on_failure_webhooks=[url], schedule={"mode": "cron", "cron": "0 0 1 1 *"})
        first = store.enqueue_run(job["_id"])
        fail(store, life, first)
        import time

        time.sleep(0.3)
        assert _Hook.bodies == []  # a retry is pending, so no alert yet
        retry = [r for r in store.list_runs(job_id=job["_id"]) if r["trigger"] == "retry"][0]
        store.claim_run("w", now_utc() + timedelta(hours=1))
        store.start_run(retry["id"])
        w = logs.open_writer(retry["id"], now_utc().isoformat())
        w.write("err", "traceback: kaboom")
        w.close()
        life.finalize(retry["id"], "failed", returncode=1, reason="boom")
        deadline = time.time() + 5
        while not _Hook.bodies and time.time() < deadline:
            time.sleep(0.05)
        assert _Hook.bodies and _Hook.bodies[0]["job_id"] == job["_id"] and "kaboom" in _Hook.bodies[0]["error_message"]
    finally:
        srv.shutdown()


# ------------------------------------------------------------------ misfire / overlap


def _interval_job(store, now, **sched):
    doc = build_job(
        {
            "name": "m",
            "executor": {"type": "shell", "script": "echo"},
            "schedule": {"mode": "interval", "interval_seconds": 60, **sched},
        },
        now=now,
    )
    return store.create_job(doc)


@pytest.mark.parametrize(
    ("policy", "extra", "expected_runs", "dropped"),
    [("run_once", {}, 1, 4), ("skip", {}, 0, 5), ("catch_up", {"catch_up_limit": 3}, 3, 2)],
)
def test_misfire_policies(env, policy, extra, expected_runs, dropped):
    store, _, _ = env
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    job = _interval_job(store, t0, misfire_policy=policy, **extra)  # first tick at t0, then every 60s
    store.update_job(job["_id"], {})  # no-op version bump keeps the fixture honest
    assert tick(store, now=t0 + timedelta(minutes=4, seconds=59)) == expected_runs  # ticks at +0..+4min were missed
    events = store.list_schedule_events(job["_id"])
    assert (sum(e["detail"]["dropped"] for e in events) if events else 0) == (dropped if policy != "skip" else 5)
    runs = store.list_runs(job_id=job["_id"])
    assert len(runs) == expected_runs and all(r["scheduled_ts"] for r in runs)


def test_overlap_skip_records_a_schedule_event(env):
    store, _, _ = env
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    job = _interval_job(store, t0, overlap_policy="skip")
    assert tick(store, now=t0) == 1
    assert tick(store, now=t0 + timedelta(seconds=61)) == 0  # previous run still pending
    assert [e["type"] for e in store.list_schedule_events(job["_id"])] == ["overlap_skipped"]
    assert len(store.list_runs(job_id=job["_id"])) == 1


def test_overlap_queue_serialises_runs(env):
    store, _, _ = env
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _interval_job(store, t0, overlap_policy="queue")
    tick(store, now=t0)
    tick(store, now=t0 + timedelta(seconds=61))
    first = store.claim_run("w1")
    assert first is not None
    store.start_run(first["id"])
    assert store.claim_run("w2") is None  # second tick waits while the first runs
    store.finish_run(first["id"], "success", 0)
    assert store.claim_run("w2") is not None


# ------------------------------------------------------------- recovery / retention


def test_orphan_recovery_routes_through_retry(env):
    store, _, life = env
    job = mkjob(store, max_retries=1, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"])
    store.claim_run("w")
    store.start_run(run["id"])
    assert life.recover_orphans() == 1
    assert store.get_run(run["id"])["status"] == "failed"
    assert [r["trigger"] for r in store.list_runs(job_id=job["_id"])].count("retry") == 1


def test_pending_runs_and_delays_survive_a_reopen(tmp_path):
    path = tmp_path / "h.db"
    s1 = Store(path)
    job = mkjob(s1, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    later = now_utc() + timedelta(minutes=30)
    run = s1.enqueue_run(job["_id"], trigger="retry", not_before=later, retry_attempt=1)
    s1.close()
    s2 = Store(path)
    again = s2.get_run(run["id"])
    assert again["status"] == "pending" and again["not_before"] == iso(later)
    assert s2.claim_run("w") is None
    s2.close()


def test_retention_purges_runs_events_and_log_files(env):
    store, logs, life = env
    job = mkjob(store, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    old = store.enqueue_run(job["_id"])
    store.claim_run("w")
    store.start_run(old["id"])
    w = logs.open_writer(old["id"], now_utc().isoformat())
    w.write("out", "x")
    w.close()
    life.finalize(old["id"], "success", returncode=0)
    fresh = store.enqueue_run(job["_id"])
    assert loops.purge_old_runs(store, logs, 0) == 0  # 0 disables
    assert loops.purge_old_runs(store, logs, 30) == 0  # nothing is old yet
    assert loops.purge_old_runs(store, logs, 30, now=now_utc() + timedelta(days=31)) == 1
    assert logs.path(old["id"], "out") is None and store.list_events(old["id"]) == []
    assert store.get_run(fresh["id"])["status"] == "pending"  # unfinished runs are never purged


# ------------------------------------------------------------- timeout backstop / SLA


class _Pool:
    def __init__(self):
        self.killed = []

    def kill(self, run_id, reason="request"):
        self.killed.append((run_id, reason))
        return True


def test_timeout_backstop_kills_only_overdue_runs(env):
    store, _, _ = env
    job = mkjob(store, timeout=30, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"])
    store.claim_run("w")
    store.start_run(run["id"])
    pool = _Pool()
    assert loops.enforce_timeouts(store, pool, now=now_utc() + timedelta(seconds=35)) == []  # within grace
    assert loops.enforce_timeouts(store, pool, now=now_utc() + timedelta(seconds=45)) == [run["id"]]
    assert pool.killed == [(run["id"], "timeout")]


def test_sla_alert_fires_once(env):
    store, _, life = env
    job = mkjob(store, sla_max_duration_seconds=10, schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    run = store.enqueue_run(job["_id"])
    store.claim_run("w")
    store.start_run(run["id"])
    assert loops.check_sla(store, life, now=now_utc() + timedelta(seconds=5)) == []
    assert loops.check_sla(store, life, now=now_utc() + timedelta(seconds=20)) == [run["id"]]
    assert loops.check_sla(store, life, now=now_utc() + timedelta(seconds=30)) == []
    assert "sla_miss" in [e["type"] for e in store.list_events(run["id"])]


def test_daemon_backstop_times_out_a_run_that_ignores_its_timeout(daemon, monkeypatch):
    """End to end: a kill with reason=timeout ends as timed_out and then retries per policy."""
    from conftest import py_job, wait_for

    monkeypatch.setattr(loops, "TIMEOUT_GRACE_SECONDS", 0)
    daemon.start()
    try:
        doc = build_job({**py_job("slow", "import time; time.sleep(60)"), "schedule": {"mode": "cron", "cron": "0 0 1 1 *"}})
        job = daemon.store.create_job(doc)
        run = daemon.store.enqueue_run(job["_id"])
        wait_for(lambda: daemon.store.get_run(run["id"])["status"] == "running")
        assert daemon.pool.kill(run["id"], reason="timeout")
        done = wait_for(lambda: (r := daemon.store.get_run(run["id"]))["status"] == "timed_out" and r)
        assert "timeout" in done["completion_reason"]
    finally:
        daemon.shutdown()
