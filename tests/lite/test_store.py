import threading
from datetime import timedelta

import pytest

from hydra_lite.store import DuplicateJobName, NotFound, Store
from hydra_lite.store.store import now_utc


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "hydra.db")
    yield s
    s.close()


def _job(store, name="j", **extra):
    return store.create_job({"name": name, "executor": {"type": "shell", "script": "echo hi"}, **extra})


def test_job_crud_and_versions(store):
    job = _job(store, schedule={"mode": "interval", "interval_seconds": 60})
    assert job["_id"] and job["name"] == "j" and job["enabled"] is True
    assert store.get_job_by_name("j")["_id"] == job["_id"]

    updated = store.update_job(job["_id"], {"schedule": {"mode": "cron", "cron": "*/5 * * * *"}}, changed_by="me")
    # shallow merge: the whole schedule object is replaced, other keys kept
    assert updated["schedule"] == {"mode": "cron", "cron": "*/5 * * * *"}
    assert updated["executor"]["script"] == "echo hi"
    versions = store.list_versions(job["_id"])
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["changed_by"] == "me"
    assert store.get_version(job["_id"], 1)["definition"]["schedule"]["mode"] == "interval"

    store.delete_job(job["_id"])
    with pytest.raises(NotFound):
        store.get_job(job["_id"])
    # history survives deletion of the job itself
    assert store.get_version(job["_id"], 1)["version"] == 1


def test_duplicate_name_and_search(store):
    _job(store, "alpha")
    _job(store, "beta")
    with pytest.raises(DuplicateJobName):
        _job(store, "alpha")
    assert [j["name"] for j in store.list_jobs(search="alp")] == ["alpha"]
    assert len(store.list_jobs()) == 2


def test_due_jobs(store):
    now = now_utc()
    due = _job(store, "due", schedule={"next_run_at": (now - timedelta(seconds=5)).isoformat()})
    _job(store, "later", schedule={"next_run_at": (now + timedelta(hours=1)).isoformat()})
    _job(store, "off", enabled=False, schedule={"next_run_at": (now - timedelta(seconds=5)).isoformat()})
    assert [j["_id"] for j in store.due_jobs(now)] == [due["_id"]]


def test_claim_orders_by_priority_then_age_and_marks_dispatched(store):
    job = _job(store)
    low = store.enqueue_run(job["_id"], priority=1)
    first_hi = store.enqueue_run(job["_id"], priority=9)
    second_hi = store.enqueue_run(job["_id"], priority=9)
    claimed = [store.claim_run("w1")["id"] for _ in range(3)]
    assert claimed == [first_hi["id"], second_hi["id"], low["id"]]
    assert store.claim_run("w1") is None
    run = store.get_run(low["id"])
    assert run["status"] == "dispatched" and run["worker_id"] == "w1" and run["queue_latency_ms"] >= 0


def test_not_before_delays_claim(store):
    job = _job(store)
    now = now_utc()
    store.enqueue_run(job["_id"], not_before=now + timedelta(minutes=5))
    assert store.claim_run("w1", now) is None
    assert store.claim_run("w1", now + timedelta(minutes=6)) is not None


def test_concurrent_claimers_never_share_a_run(store):
    job = _job(store)
    total = 40
    for _ in range(total):
        store.enqueue_run(job["_id"])
    got, lock = [], threading.Lock()

    def worker(n):
        while True:
            run = store.claim_run(f"w{n}")
            if not run:
                return
            with lock:
                got.append(run["id"])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(got) == total and len(set(got)) == total


def test_run_lifecycle_and_event_trail(store):
    job = _job(store)
    run = store.enqueue_run(job["_id"], trigger="manual", params={"A": "1"})
    assert run["params"] == {"A": "1"}
    store.claim_run("w1")
    store.start_run(run["id"], log_path="x.log")
    done = store.finish_run(run["id"], "success", exit_code=0)
    assert done["status"] == "success" and done["attempt"] == 1 and done["total_run_ms"] >= 0
    assert [e["type"] for e in store.list_events(run["id"])] == ["queued", "dispatched", "started", "success"]
    # first terminal state wins
    assert store.finish_run(run["id"], "failed", exit_code=1)["status"] == "success"
    with pytest.raises(ValueError):
        store.finish_run(run["id"], "running")


def test_list_runs_filters_and_cursor(store):
    a, b = _job(store, "a"), _job(store, "b")
    runs = [store.enqueue_run(a["_id"]) for _ in range(3)] + [store.enqueue_run(b["_id"])]
    assert len(store.list_runs(job_id=a["_id"])) == 3
    assert store.list_runs(limit=1)[0]["id"] == runs[-1]["id"]
    assert store.list_runs(status="success") == []
    page = store.list_runs(job_id=a["_id"], limit=2)
    older = store.list_runs(job_id=a["_id"], before=page[-1]["queued_at"])
    assert {r["id"] for r in page}.isdisjoint({r["id"] for r in older}) or len(older) <= 1


def test_recover_orphans_marks_active_runs_lost(store):
    job = _job(store)
    r1, r2, r3 = (store.enqueue_run(job["_id"]) for _ in range(3))
    store.claim_run("w1")
    store.claim_run("w1")
    store.start_run(r1["id"])
    lost = store.recover_orphans()
    assert set(lost) == {r1["id"], r2["id"]}
    assert store.get_run(r1["id"])["status"] == "lost"
    assert store.get_run(r3["id"])["status"] == "queued"
    assert store.active_run_count(job["_id"]) == 1


def test_workers_register_and_heartbeat(store):
    store.register_worker("w1", pid=123, max_concurrency=2, tags=["a"], capabilities=["shell"])
    store.heartbeat("w1")
    w = store.list_workers()[0]
    assert w["id"] == "w1" and w["tags"] == ["a"] and w["capabilities"] == ["shell"] and w["max_concurrency"] == 2
    with pytest.raises(NotFound):
        store.heartbeat("ghost")


def test_schema_version_guard(tmp_path):
    s = Store(tmp_path / "x.db")
    s._conn.execute("PRAGMA user_version=99")
    s.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(tmp_path / "x.db")
