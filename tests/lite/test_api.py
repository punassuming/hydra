import sys

from conftest import py_job, wait_for


def _terminal(client, run_id):
    return wait_for(lambda: (r := client.get(f"/runs/{run_id}").json())["status"] in {"success", "failed", "timed_out"} and r)


def test_health_is_open_and_advertises_lite(client):
    r = client.get("/health", headers={"x-api-key": ""})
    assert r.status_code == 200
    assert r.json()["edition"] == "lite" and r.json()["status"] == "ok"


def test_auth_required_elsewhere(client):
    assert client.get("/jobs/", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/jobs/", headers={"x-api-key": "", "authorization": "Bearer nope"}).status_code == 401
    token = client.headers["x-api-key"]
    assert client.get("/jobs/", headers={"x-api-key": "", "authorization": f"Bearer {token}"}).status_code == 200


def test_immediate_job_runs_and_records_output(client):
    job = client.post("/jobs/", json=py_job("hello", "print('hi from hydra')")).json()
    assert job["_id"] and job["domain"] == "prod"
    runs = wait_for(lambda: client.get(f"/jobs/{job['_id']}/runs").json())
    run = _terminal(client, runs[0]["_id"])
    assert run["status"] == "success" and run["returncode"] == 0
    assert "hi from hydra" in run["stdout"]
    assert run["start_ts"] and run["end_ts"] and run["duration"] >= 0
    hist = client.get("/history/").json()
    assert hist[0]["_id"] == run["_id"] and hist[0]["job_name"] == "hello"
    events = [e for e in client.app.state.daemon.store.list_events(run["_id"])]
    assert [e["type"] for e in events] == ["queued", "dispatched", "started", "success"]


def test_failure_and_params_reach_the_environment(client):
    bad = client.post(
        "/jobs/", json=py_job("bad", "import sys; sys.exit(3)", schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    ).json()
    r = client.post(f"/jobs/{bad['_id']}/run", json={"params": {"FOO": "bar"}}).json()
    run = _terminal(client, r["run_id"])
    assert run["status"] == "failed" and run["returncode"] == 3

    env = client.post(
        "/jobs/",
        json=py_job("env", "import os; print('FOO=' + os.environ['FOO'])", schedule={"mode": "cron", "cron": "0 0 1 1 *"}),
    ).json()
    r = client.post(f"/jobs/{env['_id']}/run", json={"params": {"FOO": "bar"}}).json()
    assert "FOO=bar" in _terminal(client, r["run_id"])["stdout"]


def test_param_key_validation(client):
    job = client.post("/jobs/", json=py_job("p", "pass", schedule={"mode": "cron", "cron": "0 0 1 1 *"})).json()
    assert client.post(f"/jobs/{job['_id']}/run", json={"params": {"bad-key": "x"}}).status_code == 422


def test_kill_running_run(client):
    code = f"import time; print('started', flush=True); time.sleep(60)  # {sys.version_info.major}"
    job = client.post("/jobs/", json=py_job("sleeper", code)).json()
    run_id = wait_for(lambda: [r for r in client.get(f"/jobs/{job['_id']}/runs").json() if r["status"] == "running"])[0]["_id"]
    assert client.post(f"/runs/{run_id}/kill").json()["signal"] == "kill_sent"
    run = _terminal(client, run_id)
    assert run["status"] == "failed" and run["completion_reason"] == "killed by request"
    assert "killed" in [e["type"] for e in client.app.state.daemon.store.list_events(run_id)]
    assert client.post(f"/runs/{run_id}/kill").status_code == 404


def test_validation_and_duplicate_names(client):
    assert (
        client.post("/jobs/validate", json={"name": "x", "executor": {"type": "shell", "script": " "}}).json()["valid"] is False
    )
    assert client.post("/jobs/", json={"name": "x", "executor": {"type": "shell", "script": " "}}).status_code == 422
    assert client.post("/jobs/", json={"name": "x", "schedule": {"mode": "cron", "cron": "bogus"}}).status_code == 422
    body = py_job("dup", "pass", schedule={"mode": "cron", "cron": "0 0 1 1 *"})
    assert client.post("/jobs/", json=body).status_code == 200
    assert client.post("/jobs/", json=body).status_code == 409


def test_update_keeps_schedule_and_records_versions(client):
    job = client.post("/jobs/", json=py_job("sched", "pass", schedule={"mode": "interval", "interval_seconds": 3600})).json()
    first_next = job["schedule"]["next_run_at"]
    updated = client.put(f"/jobs/{job['_id']}", json={"priority": 9}).json()
    assert updated["priority"] == 9 and updated["schedule"]["next_run_at"] == first_next
    versions = client.get(f"/jobs/{job['_id']}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    assert client.get(f"/jobs/{job['_id']}/versions/1").json()["definition"]["priority"] == 5


def test_enable_disable(client):
    job = client.post("/jobs/", json=py_job("toggle", "pass", schedule={"mode": "interval", "interval_seconds": 3600})).json()
    off = client.post(f"/jobs/{job['_id']}/disable").json()
    assert off["schedule"]["enabled"] is False and off["schedule"]["next_run_at"] is None
    on = client.post(f"/jobs/{job['_id']}/enable").json()
    assert on["schedule"]["enabled"] is True and on["schedule"]["next_run_at"]


def test_delete_and_missing(client):
    job = client.post("/jobs/", json=py_job("gone", "pass", schedule={"mode": "cron", "cron": "0 0 1 1 *"})).json()
    assert client.delete(f"/jobs/{job['_id']}").json()["deleted"] is True
    assert client.get(f"/jobs/{job['_id']}").status_code == 404
    assert client.get("/runs/nope").status_code == 404


def test_workers_and_unsupported_areas(client):
    workers = client.get("/workers/").json()
    assert workers and workers[0]["connectivity_status"] == "online" and workers[0]["max_concurrency"] == 2
    wid = workers[0]["worker_id"]
    assert client.post(f"/workers/{wid}/state", json={"state": "draining"}).json()["state"] == "draining"
    assert client.post(f"/workers/{wid}/state", json={"state": "online"}).status_code == 200
    assert client.post(f"/workers/{wid}/state", json={"state": "weird"}).status_code == 422
    for path in ("/admin/domains", "/domain/settings", "/credentials/", "/ai/generate_job"):
        assert client.get(path).status_code == 501


def test_log_offsets(client):
    job = client.post("/jobs/", json=py_job("logs", "print('line1'); print('line2')")).json()
    run = _terminal(client, wait_for(lambda: client.get(f"/jobs/{job['_id']}/runs").json())[0]["_id"])
    first = client.get(f"/runs/{run['_id']}/logs").json()
    assert first["done"] is True and "line1" in first["stdout"]
    again = client.get(f"/runs/{run['_id']}/logs", params={"out_offset": first["out_offset"]}).json()
    assert again["stdout"] == ""
