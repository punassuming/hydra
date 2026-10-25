"""sql/sensor executors and bypass_concurrency in the lite edition."""

import http.server
import sqlite3
import threading
import time

import pytest
from conftest import make_config, py_job, start_live, stop_live, wait_for

from cli._client import HydraClient
from hydra_lite.daemon.runtime import Daemon

CRON = {"mode": "cron", "cron": "0 0 1 1 *"}


def job_body(name, executor, **extra):
    return {"name": name, "executor": executor, "schedule": CRON, **extra}


def terminal(client, run_id, timeout=30):
    return wait_for(
        lambda: (r := client.get(f"/runs/{run_id}").json())["status"] in {"success", "failed", "timed_out"} and r, timeout=timeout
    )


# ------------------------------------------------------------------------------------------ validation


def test_sql_and_sensor_jobs_are_accepted(client):
    sql = job_body("sql", {"type": "sql", "query": "select 1", "connection_uri": "sqlite:///x.db"})
    sensor = job_body("sensor", {"type": "sensor", "target": "http://127.0.0.1:1/ok"})
    assert client.post("/jobs/", json=sql).status_code == 200
    assert client.post("/jobs/", json=sensor).status_code == 200


@pytest.mark.parametrize(
    "executor",
    [
        {"type": "sql", "query": "select 1", "credential_ref": "prod-db"},
        {"type": "sensor", "sensor_type": "sql", "target": "select 1", "credential_ref": "prod-db"},
        {"type": "http", "url": "http://x", "credential_ref": "api"},
    ],
)
def test_credential_ref_is_rejected_with_an_actionable_message(client, executor):
    r = client.post("/jobs/", json=job_body("cred", executor))
    assert r.status_code == 422 and "credential store" in str(r.json()["detail"])


def test_credential_ref_is_tolerated_when_the_uri_is_inline_and_git_refs_are_rejected(client):
    both = job_body("both", {"type": "sql", "query": "select 1", "connection_uri": "sqlite:///x.db", "credential_ref": "unused"})
    assert client.post("/jobs/", json=both).status_code == 200
    git = {
        **job_body("git", {"type": "shell", "script": "ls"}),
        "source": {"url": "https://example.com/r.git", "credential_ref": "pat"},
    }
    r = client.post("/jobs/", json=git)
    assert r.status_code == 422 and "source.credential_ref" in str(r.json()["detail"])


def test_connection_uri_is_masked_in_responses(client):
    job = client.post(
        "/jobs/", json=job_body("masked", {"type": "sql", "query": "select 1", "connection_uri": "postgresql://u:pw@h/db"})
    ).json()
    assert job["executor"]["connection_uri"] == "********"
    assert client.get(f"/jobs/{job['_id']}").json()["executor"]["connection_uri"] == "********"


# ------------------------------------------------------------------------------------------ sql


def test_sql_job_runs_a_query(client, tmp_path):
    pytest.importorskip("sqlalchemy")
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("create table t(n integer)")
    con.executemany("insert into t values (?)", [(1,), (2,), (3,)])
    con.commit()
    con.close()
    job = client.post(
        "/jobs/",
        json=job_body(
            "count", {"type": "sql", "query": "select count(*) as n from t", "connection_uri": f"sqlite:///{db.as_posix()}"}
        ),
    ).json()
    run = terminal(client, client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"])
    assert run["status"] == "success" and '"n": 3' in run["stdout"]


def _register(c, wid, caps):
    r = c.post("/internal/register", json={"worker_id": wid, "max_concurrency": 2, "meta": {"os": "linux", "capabilities": caps}})
    assert r.status_code == 200


def test_sql_run_waits_for_a_worker_that_advertises_the_sql_capability(proto_client):
    c, d = proto_client
    from hydra_lite.jobs import build_job

    job = d.store.create_job(
        build_job(job_body("needs-sql", {"type": "sql", "query": "select 1", "connection_uri": "sqlite://"}))
    )
    d.store.enqueue_run(job["_id"])
    _register(c, "lean", "shell,python,http")
    assert c.post("/internal/claim", json={"worker_id": "lean", "capacity": 2, "wait": 0}).json()["runs"] == []
    _register(c, "sql-capable", "shell,python,http,sql")
    assert len(c.post("/internal/claim", json={"worker_id": "sql-capable", "capacity": 2, "wait": 0}).json()["runs"]) == 1


# ------------------------------------------------------------------------------------------ sensor


@pytest.fixture()
def flag_server():
    state = {"code": 503}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(state["code"])
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/", state
    srv.shutdown()


def test_http_sensor_succeeds_when_the_condition_is_met(client, flag_server):
    url, state = flag_server
    job = client.post(
        "/jobs/",
        json=job_body("wait-for-it", {"type": "sensor", "target": url, "poll_interval_seconds": 1, "timeout_seconds": 30}),
    ).json()
    run_id = client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"]
    wait_for(lambda: client.get(f"/runs/{run_id}").json()["status"] == "running")
    time.sleep(1.5)
    assert client.get(f"/runs/{run_id}").json()["status"] == "running"  # still polling a 503
    state["code"] = 200
    run = terminal(client, run_id)
    assert run["status"] == "success" and "condition_met" in run["stdout"]


def test_http_sensor_times_out_and_can_be_killed(client, flag_server):
    url, _ = flag_server
    quick = client.post(
        "/jobs/", json=job_body("quick", {"type": "sensor", "target": url, "poll_interval_seconds": 1, "timeout_seconds": 2})
    ).json()
    run = terminal(client, client.post(f"/jobs/{quick['_id']}/run", json={}).json()["run_id"])
    assert run["status"] == "failed" and "timed out" in run["stderr"]
    long = client.post(
        "/jobs/", json=job_body("long", {"type": "sensor", "target": url, "poll_interval_seconds": 1, "timeout_seconds": 600})
    ).json()
    run_id = client.post(f"/jobs/{long['_id']}/run", json={}).json()["run_id"]
    wait_for(lambda: client.get(f"/runs/{run_id}").json()["status"] == "running")
    client.post(f"/runs/{run_id}/kill")
    assert terminal(client, run_id, timeout=15)["completion_reason"] == "killed by request"


# ------------------------------------------------------------------------------------------ bypass_concurrency


def _sleeper(name, seconds, **extra):
    return {**py_job(name, f"import time; time.sleep({seconds})"), "schedule": CRON, **extra}


def test_bypass_job_runs_while_every_slot_is_busy_in_process(client):
    """The pool has 2 slots: two long normal jobs fill them; a bypass job still runs, a normal one waits."""
    a = client.post("/jobs/", json=_sleeper("a", 60)).json()
    b = client.post("/jobs/", json=_sleeper("b", 60)).json()
    ra, rb = (client.post(f"/jobs/{j['_id']}/run", json={}).json()["run_id"] for j in (a, b))
    wait_for(lambda: all(client.get(f"/runs/{r}").json()["status"] == "running" for r in (ra, rb)))
    fast = client.post(
        "/jobs/", json={**py_job("fast", "print('bypassed')"), "schedule": CRON, "bypass_concurrency": True}
    ).json()
    plain = client.post("/jobs/", json={**py_job("plain", "print('waited')"), "schedule": CRON}).json()
    r_plain = client.post(f"/jobs/{plain['_id']}/run", json={}).json()["run_id"]
    r_fast = client.post(f"/jobs/{fast['_id']}/run", json={}).json()["run_id"]
    done = terminal(client, r_fast, timeout=15)
    assert done["status"] == "success" and "bypassed" in done["stdout"]
    assert client.get(f"/runs/{r_plain}").json()["status"] == "pending"  # no free slot, not a bypass job
    for r in (ra, rb):
        client.post(f"/runs/{r}/kill")
    assert "waited" in terminal(client, r_plain)["stdout"]  # slots freed -> the normal job finally runs


def test_bypass_claims_over_the_protocol(proto_client):
    c, d = proto_client
    from hydra_lite.jobs import build_job

    byp = d.store.create_job(build_job({**py_job("byp", "pass"), "schedule": CRON, "bypass_concurrency": True}))
    norm = d.store.create_job(build_job({**py_job("norm", "pass"), "schedule": CRON}))
    _register(c, "w", "shell,python,http")
    d.store.enqueue_run(norm["_id"], priority=9)
    d.store.enqueue_run(byp["_id"], priority=1)
    claim = lambda **kw: c.post("/internal/claim", json={"worker_id": "w", "wait": 0, **kw}).json()["runs"]  # noqa: E731
    assert claim(capacity=0, bypass=0) == []  # full, no extra room
    got = claim(capacity=0, bypass=1)
    assert [e["job"]["name"] for e in got] == ["byp"]  # only the bypass job may exceed capacity, despite lower priority
    assert [e["job"]["name"] for e in claim(capacity=1, bypass=0)] == ["norm"]


def test_bypass_respects_the_extra_cap_with_real_worker_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULER_BYPASS_MAX_EXTRA", "1")
    d = Daemon(make_config(tmp_path, worker_mode="subprocess", default_workers=1, max_workers=1, max_concurrency=1))
    url, server, thread = start_live(d)
    try:
        api = HydraClient(url, token=d.token, timeout=30)
        wait_for(lambda: any(w["connectivity_status"] == "online" for w in api.request("GET", "/workers/")), 30)

        def submit(name, code, bypass=False):
            return api.request("POST", "/jobs/", body={**py_job(name, code), "schedule": CRON, "bypass_concurrency": bypass})

        def run(job):
            return api.request("POST", f"/jobs/{job['_id']}/run", body={})["run_id"]

        def status(rid):
            return api.request("GET", f"/runs/{rid}")["status"]

        blocker = run(submit("blocker", "import time; time.sleep(120)"))
        wait_for(lambda: status(blocker) == "running")
        first = run(submit("bypass-1", "import time; time.sleep(120)", bypass=True))
        wait_for(lambda: status(first) == "running", 20)  # worker has 1 slot, both run
        second = run(submit("bypass-2", "print('second')", bypass=True))
        time.sleep(3)
        assert status(second) == "pending"  # SCHEDULER_BYPASS_MAX_EXTRA=1: only one extra
        api.request("POST", f"/runs/{first}/kill")
        wait_for(lambda: status(second) == "success", 30)  # extra room freed
        api.request("POST", f"/runs/{blocker}/kill")
    finally:
        stop_live(server, thread)
