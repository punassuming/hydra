"""Real supervised worker processes."""

import os
import signal
import sys
from datetime import timedelta

from conftest import py_job, wait_for

from hydra_lite.jobs import build_job
from hydra_lite.loops import reap_workers
from hydra_lite.store.store import now_utc

CRON = {"mode": "cron", "cron": "0 0 1 1 *"}


def _submit(api, name, code, **extra):
    return api.request("POST", "/jobs/", body={**py_job(name, code), "schedule": CRON, **extra})


def _run(api, job, params=None):
    return api.request("POST", f"/jobs/{job['_id']}/run", body={"params": params or {}})["run_id"]


def _wait_status(api, run_id, *statuses, timeout=30):
    return wait_for(lambda: (r := api.request("GET", f"/runs/{run_id}"))["status"] in statuses and r, timeout=timeout)


def test_run_executes_in_a_supervised_process(sub_live):
    api, d = sub_live
    job = _submit(api, "e2e", "import os; print('P=' + os.environ['P'], os.getpid())")
    run_id = _run(api, job, {"P": "7"})
    run = _wait_status(api, run_id, "success", "failed")
    assert run["status"] == "success" and "P=7" in run["stdout"]
    assert str(os.getpid()) not in run["stdout"].split()[-1]  # ran in a different process than the daemon
    assert [e["type"] for e in d.store.list_events(run_id)] == ["queued", "dispatched", "started", "success"]
    [w] = api.request("GET", "/workers/")
    assert w["hostname"] and "python" in w["capabilities"] and w["worker_id"].startswith("lite-")
    assert run["worker_id"] == w["worker_id"] and run["total_run_ms"] is not None


def test_failure_returncode_and_output_are_reported(sub_live):
    api, _ = sub_live
    job = _submit(api, "bad", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(4)")
    run = _wait_status(api, _run(api, job), "failed")
    assert run["returncode"] == 4 and "out" in run["stdout"] and "err" in run["stderr"]


def test_in_worker_retries_are_recorded(sub_live):
    api, d = sub_live
    job = _submit(api, "flaky", "import sys; sys.exit(1)", retries=2)
    run_id = _run(api, job)
    run = _wait_status(api, run_id, "failed")
    assert run["attempt"] == 3
    assert [e["type"] for e in d.store.list_events(run_id)].count("retry") == 2


def test_kill_reaches_a_running_process_via_heartbeat(sub_live):
    api, _ = sub_live
    job = _submit(api, "sleeper", "import time; print('up', flush=True); time.sleep(120)")
    run_id = _run(api, job)
    _wait_status(api, run_id, "running")
    api.request("POST", f"/runs/{run_id}/kill")
    run = _wait_status(api, run_id, "failed", timeout=15)
    assert run["completion_reason"] == "killed by request"


def test_worker_crash_marks_the_run_lost_retries_it_and_the_supervisor_restarts_the_worker(sub_live, tmp_path):
    api, d = sub_live
    marker = tmp_path / "first.txt"
    code = (
        f"import os, time; m = {str(marker)!r}\n"
        "if os.path.exists(m):\n    print('second attempt')\n"
        "else:\n    open(m, 'w').write('x'); print('first', flush=True); time.sleep(120)\n"
    )
    job = _submit(api, "crashy", code, max_retries=1)
    run_id = _run(api, job)
    _wait_status(api, run_id, "running")
    wait_for(marker.exists)  # the job really started (the marker is how attempt two tells it is a retry)
    [w] = api.request("GET", "/workers/")
    os.kill(w["pid"], signal.SIGKILL)
    lost = _wait_status(api, run_id, "failed", timeout=30)
    assert lost["completion_reason"].startswith("lost: worker")
    retry = wait_for(lambda: [r for r in api.request("GET", f"/jobs/{job['_id']}/runs") if r["_id"] != run_id], timeout=15)[0]
    done = _wait_status(api, retry["_id"], "success", timeout=60)  # restarted worker picks the retry up
    assert "second attempt" in done["stdout"] and done["retry_attempt"] == 1


def test_spawn_and_stop_workers_and_limit(sub_live):
    api, d = sub_live
    ids = api.request("POST", "/workers/spawn", body={"count": 1, "tags": ["extra"]})["spawned"]
    assert len(ids) == 1
    wait_for(
        lambda: any(w["worker_id"] == ids[0] and w["connectivity_status"] == "online" for w in api.request("GET", "/workers/")),
        30,
    )
    api.request("POST", "/workers/spawn", body={"count": 1})
    try:
        api.request("POST", "/workers/spawn", body={"count": 1})
        raise AssertionError("limit not enforced")
    except Exception as exc:
        assert "limit" in str(exc)
    assert api.request("POST", f"/workers/{ids[0]}/stop")["stopping"] is True
    wait_for(lambda: ids[0] not in d.supervisor.workers, timeout=45)  # drained, exited and forgotten


def test_tagged_job_waits_for_a_matching_worker(sub_live):
    api, _ = sub_live
    job = _submit(api, "tagged", "print('gpu job')", affinity={"tags": ["gpu"]})
    run_id = _run(api, job)
    import time

    time.sleep(3)
    assert api.request("GET", f"/runs/{run_id}")["status"] == "pending"
    api.request("POST", "/workers/spawn", body={"count": 1, "tags": ["gpu"]})
    assert "gpu job" in _wait_status(api, run_id, "success", timeout=45)["stdout"]


def test_on_demand_scaling_and_idle_stop(tmp_path):
    """No permanent workers: pending work spawns one, and it is stopped again once idle."""
    from conftest import make_config, start_live, stop_live

    from cli._client import HydraClient
    from hydra_lite.daemon.runtime import Daemon

    d = Daemon(make_config(tmp_path, worker_mode="subprocess", default_workers=0, max_workers=2, idle_stop_seconds=4))
    url, server, thread = start_live(d)
    try:
        api = HydraClient(url, token=d.token, timeout=30)
        job = _submit(api, "ondemand", "print('scaled')")
        assert "scaled" in _wait_status(api, _run(api, job), "success", timeout=60)["stdout"]
        wait_for(lambda: not d.supervisor.workers, timeout=60)  # idle worker drained and removed
    finally:
        stop_live(server, thread)


# ---------------------------------------------------------------- reaper (deterministic, no processes)


def test_reaper_requeues_unstarted_runs_and_fails_running_ones(tmp_path):
    from hydra_lite.lifecycle import Lifecycle
    from hydra_lite.logs import LogStore
    from hydra_lite.store import Store

    store = Store(tmp_path / "h.db")
    life = Lifecycle(store, LogStore(tmp_path / "logs"))
    job = store.create_job(build_job({**py_job("r", "pass"), "max_retries": 1, "schedule": CRON}))
    store.register_worker("w1", 1, 2)
    unstarted, started = store.enqueue_run(job["_id"]), store.enqueue_run(job["_id"])
    store.claim_run("w1")
    store.claim_run("w1")
    store.start_run(started["id"])
    assert reap_workers(store, life, ttl=3, prune_seconds=1800) == []  # still fresh
    later = now_utc() + timedelta(seconds=30)
    assert reap_workers(store, life, ttl=3, prune_seconds=1800, now=later) == ["w1"]
    assert store.get_run(unstarted["id"])["status"] == "pending"
    lost = store.get_run(started["id"])
    assert lost["status"] == "failed" and lost["completion_reason"].startswith("lost: worker w1")
    assert any(r["trigger"] == "retry" for r in store.list_runs(job_id=job["_id"]))
    reap_workers(store, life, ttl=3, prune_seconds=1800, now=later)  # idempotent
    assert len([r for r in store.list_runs(job_id=job["_id"]) if r["trigger"] == "retry"]) == 1
    assert store.list_workers()  # not pruned yet
    # once gone long enough and idle, the worker record is forgotten
    store.requeue_run(unstarted["id"], "x")
    reap_workers(store, life, ttl=3, prune_seconds=10, now=later + timedelta(hours=1))
    assert [w for w in store.list_workers() if w["id"] == "w1"] == [] or sys.platform == "win32"
    store.close()


def test_restarted_worker_under_the_same_id_does_not_hide_lost_runs(tmp_path):
    """The reaper never sees such a worker go stale, so registration and heartbeats must reconcile its runs."""
    from hydra_lite.lifecycle import Lifecycle
    from hydra_lite.logs import LogStore
    from hydra_lite.loops import reconcile_worker
    from hydra_lite.store import Store

    store = Store(tmp_path / "h.db")
    life = Lifecycle(store, LogStore(tmp_path / "logs"))
    job = store.create_job(build_job({**py_job("c", "pass"), "max_retries": 1, "schedule": CRON}))
    store.register_worker("w1", 1, 2)
    running, dispatched = store.enqueue_run(job["_id"]), store.enqueue_run(job["_id"])
    store.claim_run("w1")
    store.claim_run("w1")
    store.start_run(running["id"])
    # inside the grace window nothing is touched (a run may have just been claimed/started)
    assert reconcile_worker(store, life, "w1", set()) == []
    # a worker that reports it holds the run keeps it
    assert reconcile_worker(store, life, "w1", {running["id"], dispatched["id"]}, now=now_utc() + timedelta(minutes=5)) == []
    # a fresh registration (grace off) recovers both: the started run is lost (and retried), the other requeued
    assert set(reconcile_worker(store, life, "w1", set(), grace=False)) == {running["id"], dispatched["id"]}
    assert store.get_run(running["id"])["status"] == "failed"
    assert store.get_run(dispatched["id"])["status"] == "pending" and store.get_run(dispatched["id"])["dispatched_at"] is None
    assert [r["trigger"] for r in store.list_runs(job_id=job["_id"])].count("retry") == 1
    store.close()


def test_sigterm_drains_in_flight_runs_before_the_worker_exits(sub_live):
    api, _ = sub_live
    job = _submit(api, "drain", "import time; print('start', flush=True); time.sleep(4); print('finished')")
    run_id = _run(api, job)
    _wait_status(api, run_id, "running")
    [w] = api.request("GET", "/workers/")
    os.kill(w["pid"], signal.SIGTERM)
    run = _wait_status(api, run_id, "success", "failed", timeout=30)
    assert run["status"] == "success" and "finished" in run["stdout"]
