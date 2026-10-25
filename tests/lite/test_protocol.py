"""The /internal worker protocol, exercised by hand (the test plays the worker)."""

from conftest import py_job

from hydra_lite.jobs import build_job


def _job(d, name="p", **extra):
    return d.store.create_job(
        build_job({**py_job(name, "print('hi')"), "schedule": {"mode": "cron", "cron": "0 0 1 1 *"}, **extra})
    )


def _register(c, wid="w1", tags="", caps="shell,python,http", **meta):
    body = {
        "worker_id": wid,
        "max_concurrency": 2,
        "meta": {"os": "linux", "tags": tags, "capabilities": caps, "hostname": "h", **meta},
    }
    r = c.post("/internal/register", json=body)
    assert r.status_code == 200 and r.json()["state"] == "online"
    return r.json()


def test_full_run_lifecycle_over_the_protocol(proto_client):
    c, d = proto_client
    job = _job(d)
    _register(c)
    run = d.store.enqueue_run(job["_id"], params={"A": "1"})
    reply = c.post("/internal/claim", json={"worker_id": "w1", "capacity": 2, "wait": 0}).json()
    [env] = reply["runs"]
    assert env["run_id"] == run["id"] and env["job"]["name"] == "p" and env["params"] == {"A": "1"}

    base = {"run_id": run["id"], "job_id": job["_id"], "worker_id": "w1"}
    assert c.post("/internal/events", json={**base, "type": "run_start"}).json()["ok"] is True
    c.post("/internal/logs", json={"chunks": [{"run_id": run["id"], "stream": "stdout", "text": "hello\n"}]})
    end = {
        **base,
        "type": "run_end",
        "status": "success",
        "returncode": 0,
        "attempt": 1,
        "completion_reason": "ok",
        "source_fetch_ms": 12.5,
    }
    assert c.post("/internal/events", json=end).json()["ok"] is True
    got = c.get(f"/runs/{run['id']}").json()
    assert got["status"] == "success" and "hello" in got["stdout"]
    assert d.store.get_run(run["id"])["source_fetch_ms"] == 12.5
    assert [e["type"] for e in d.store.list_events(run["id"])] == ["queued", "dispatched", "started", "success"]


def test_duplicate_run_end_is_idempotent_and_does_not_double_retry(proto_client):
    c, d = proto_client
    job = _job(d, max_retries=2)
    _register(c)
    run = d.store.enqueue_run(job["_id"])
    c.post("/internal/claim", json={"worker_id": "w1", "capacity": 1, "wait": 0})
    base = {"run_id": run["id"], "job_id": job["_id"], "worker_id": "w1"}
    c.post("/internal/events", json={**base, "type": "run_start"})
    end = {**base, "type": "run_end", "status": "failed", "returncode": 1, "attempt": 1, "completion_reason": "boom"}
    c.post("/internal/events", json=end)
    c.post("/internal/events", json=end)
    assert [r["trigger"] for r in d.store.list_runs(job_id=job["_id"])].count("retry") == 1


def test_events_from_a_non_owner_are_ignored_and_bad_events_rejected(proto_client):
    c, d = proto_client
    job = _job(d)
    _register(c)
    run = d.store.enqueue_run(job["_id"])
    c.post("/internal/claim", json={"worker_id": "w1", "capacity": 1, "wait": 0})
    spoof = {"run_id": run["id"], "job_id": job["_id"], "worker_id": "someone-else", "type": "run_end", "status": "success"}
    assert c.post("/internal/events", json=spoof).json()["ok"] is False
    assert d.store.get_run(run["id"])["status"] == "dispatched"
    assert (
        c.post(
            "/internal/events", json={"type": "run_end", "run_id": run["id"], "worker_id": "w1", "status": "killed"}
        ).status_code
        == 422
    )
    assert c.post("/internal/events", json={"type": "nope", "run_id": run["id"]}).status_code == 422
    assert c.post("/internal/events", json={"type": "run_start", "run_id": "missing"}).status_code == 404


def test_claim_honours_affinity_and_capabilities(proto_client):
    c, d = proto_client
    gpu = _job(d, "gpu", affinity={"tags": ["gpu"]})
    plain = _job(d, "plain")
    _register(c, "w-plain", tags="")
    _register(c, "w-gpu", tags="gpu")
    d.store.enqueue_run(gpu["_id"], priority=9)
    d.store.enqueue_run(plain["_id"], priority=1)
    first = c.post("/internal/claim", json={"worker_id": "w-plain", "capacity": 5, "wait": 0}).json()["runs"]
    assert [e["job"]["name"] for e in first] == ["plain"]  # the higher-priority gpu run is skipped, not blocking
    second = c.post("/internal/claim", json={"worker_id": "w-gpu", "capacity": 5, "wait": 0}).json()["runs"]
    assert [e["job"]["name"] for e in second] == ["gpu"]


def test_claim_respects_draining_and_unknown_workers(proto_client):
    c, d = proto_client
    job = _job(d)
    _register(c)
    d.store.enqueue_run(job["_id"])
    d.store.set_worker_state("w1", "draining")
    assert c.post("/internal/claim", json={"worker_id": "w1", "capacity": 1, "wait": 0}).json()["runs"] == []
    assert c.post("/internal/claim", json={"worker_id": "ghost", "capacity": 1, "wait": 0}).status_code == 404
    assert c.post("/internal/heartbeat", json={"worker_id": "ghost", "running_run_ids": []}).status_code == 404


def test_claim_long_polls_until_work_arrives(proto_client):
    import threading
    import time

    c, d = proto_client
    job = _job(d)
    _register(c)
    threading.Timer(0.6, lambda: d.store.enqueue_run(job["_id"])).start()
    t0 = time.time()
    runs = c.post("/internal/claim", json={"worker_id": "w1", "capacity": 1, "wait": 5}).json()["runs"]
    assert len(runs) == 1 and 0.4 < time.time() - t0 < 4


def test_heartbeat_delivers_kills_and_flags_orphans(proto_client):
    c, d = proto_client
    job = _job(d)
    _register(c)
    run = d.store.enqueue_run(job["_id"])
    c.post("/internal/claim", json={"worker_id": "w1", "capacity": 1, "wait": 0})
    base = {"run_id": run["id"], "job_id": job["_id"], "worker_id": "w1"}
    c.post("/internal/events", json={**base, "type": "run_start"})
    assert c.post("/internal/heartbeat", json={"worker_id": "w1", "running_run_ids": [run["id"]]}).json()["kill"] == []
    assert c.post(f"/runs/{run['id']}/kill").json()["signal"] == "kill_sent"
    hb = c.post("/internal/heartbeat", json={"worker_id": "w1", "running_run_ids": [run["id"]]}).json()
    assert hb["kill"] == [{"run_id": run["id"], "reason": "request"}]
    # a run the daemon doesn't assign to this worker (e.g. reaped, then the worker came back) must be stopped
    hb = c.post("/internal/heartbeat", json={"worker_id": "w1", "running_run_ids": ["not-a-run"]}).json()
    assert hb["kill"] == [{"run_id": "not-a-run", "reason": "orphaned"}]


def test_workers_list_serves_the_registered_metadata(proto_client):
    c, d = proto_client
    _register(
        c, tags="a,b", hostname="box-7", ip="10.1.2.3", subnet="10.1.2", worker_protocol_version="0.9", allowed_users="alice"
    )
    [w] = c.get("/workers/").json()
    assert w["hostname"] == "box-7" and w["tags"] == ["a", "b"] and w["allowed_users"] == ["alice"]
    assert w["protocol_mismatch"] is True and w["worker_protocol_version"] == "0.9"
