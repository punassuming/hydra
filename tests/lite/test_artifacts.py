"""Artifacts: publish through stdout, store, and trigger subscribers (same contract as the full edition)."""

import json

import pytest
from conftest import py_job, wait_for

from worker.utils.artifacts import ARTIFACT_PREFIX, parse_artifact_marker

CRON = {"mode": "cron", "cron": "0 0 1 1 *"}


def producer_code(name="daily_export", metadata=None):
    payload = json.dumps({"name": name, "metadata": metadata or {"rows": 500}})
    return f"print('before'); print({ARTIFACT_PREFIX + ' ' + payload!r}); print('after')"


def terminal(client, run_id, timeout=30):
    return wait_for(lambda: (r := client.get(f"/runs/{run_id}").json())["status"] in {"success", "failed"} and r, timeout=timeout)


# ------------------------------------------------------------------------------ the shared parser


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("hello", None),
        ("  not a marker __HYDRA_ARTIFACT__: {}", None),
        (f'{ARTIFACT_PREFIX} {{"name": "a", "metadata": {{"n": 1}}}}\n', (True, "a", {"n": 1})),
        (f'  {ARTIFACT_PREFIX}{{"name": "  spaced  "}}', (True, "spaced", {})),
        (f'{ARTIFACT_PREFIX} {{"metadata": {{}}}}', (True, "", {})),  # valid but names nothing: swallowed
        (f"{ARTIFACT_PREFIX} {{bad json}}", (False, "", None)),  # malformed: the caller logs the raw line
        (f"{ARTIFACT_PREFIX} [1, 2]", (False, "", None)),
    ],
)
def test_marker_parsing(line, expected):
    marker = parse_artifact_marker(line)
    assert (marker if marker is None else (marker.valid, marker.name, marker.metadata)) == expected


# ------------------------------------------------------------------------------ lite behaviour


def test_published_artifact_is_stored_hidden_from_the_log_and_triggers_subscribers(client):
    consumer = client.post(
        "/jobs/",
        json={
            **py_job("consumer", "import os; print('got ' + os.environ['HYDRA_UPSTREAM_ARTIFACT_METADATA'])"),
            "schedule": CRON,
            "triggers_on_artifacts": ["daily_export"],
        },
    ).json()
    off = client.post(
        "/jobs/",
        json={**py_job("off", "pass"), "schedule": {**CRON, "enabled": False}, "triggers_on_artifacts": ["daily_export"]},
    ).json()
    producer = client.post("/jobs/", json={**py_job("producer", producer_code()), "schedule": CRON}).json()
    run_id = client.post(f"/jobs/{producer['_id']}/run", json={}).json()["run_id"]
    produced = terminal(client, run_id)
    assert produced["status"] == "success"
    assert "before" in produced["stdout"] and "after" in produced["stdout"] and ARTIFACT_PREFIX not in produced["stdout"]

    art = client.get("/artifacts/daily_export").json()
    assert art["metadata"] == {"rows": 500} and art["last_run_id"] == run_id and art["last_job_id"] == producer["_id"]
    assert [a["name"] for a in client.get("/artifacts/").json()] == ["daily_export"]

    runs = wait_for(lambda: client.get(f"/jobs/{consumer['_id']}/runs").json())
    done = terminal(client, runs[0]["_id"])
    assert done["status"] == "success" and '"rows": 500' in done["stdout"]
    assert client.get(f"/jobs/{off['_id']}/runs").json() == []  # a disabled subscriber is skipped
    events = client.get(f"/runs/{runs[0]['_id']}/events").json()
    assert [e["type"] for e in events][:2] == ["queued", "triggered_by"] and events[1]["detail"]["artifact"] == "daily_export"


def test_a_job_is_not_retriggered_by_its_own_artifact(client):
    code = producer_code("loop")
    job = client.post("/jobs/", json={**py_job("selfish", code), "schedule": CRON, "triggers_on_artifacts": ["loop"]}).json()
    run_id = client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"]
    terminal(client, run_id)
    import time

    time.sleep(1.5)
    assert len(client.get(f"/jobs/{job['_id']}/runs").json()) == 1  # the full edition would loop forever here


def test_malformed_marker_is_logged_and_publishes_nothing(client):
    job = client.post("/jobs/", json={**py_job("bad", f"print({ARTIFACT_PREFIX + ' {oops}'!r})"), "schedule": CRON}).json()
    run = terminal(client, client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"])
    assert "{oops}" in run["stdout"] and client.get("/artifacts/").json() == []
    assert client.get("/artifacts/nope").status_code == 404


def test_later_publication_updates_the_record(client):
    job = client.post("/jobs/", json={**py_job("again", producer_code("x", {"v": 1})), "schedule": CRON}).json()
    terminal(client, client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"])
    client.put(f"/jobs/{job['_id']}", json={"executor": {"type": "python", "code": producer_code("x", {"v": 2})}})
    terminal(client, client.post(f"/jobs/{job['_id']}/run", json={}).json()["run_id"])
    assert client.get("/artifacts/x").json()["metadata"] == {"v": 2}


def test_artifact_event_over_the_worker_protocol(proto_client):
    c, d = proto_client
    from hydra_lite.jobs import build_job

    consumer = d.store.create_job(build_job({**py_job("c", "pass"), "schedule": CRON, "triggers_on_artifacts": ["report"]}))
    producer = d.store.create_job(build_job({**py_job("p", "pass"), "schedule": CRON}))
    c.post(
        "/internal/register",
        json={"worker_id": "w", "max_concurrency": 1, "meta": {"os": "linux", "capabilities": "python,shell"}},
    )
    run = d.store.enqueue_run(producer["_id"])
    c.post("/internal/claim", json={"worker_id": "w", "capacity": 1, "wait": 0})
    base = {"run_id": run["id"], "job_id": producer["_id"], "worker_id": "w"}
    c.post("/internal/events", json={**base, "type": "run_start"})
    assert c.post(
        "/internal/events", json={**base, "type": "artifact_emitted", "artifact_name": "report", "metadata": {"k": "v"}}
    ).json()["ok"]
    assert c.post("/internal/events", json={**base, "type": "artifact_emitted", "artifact_name": " "}).status_code == 422
    [triggered] = d.store.list_runs(job_id=consumer["_id"])
    assert triggered["trigger"] == "artifact" and json.loads(triggered["params"]["HYDRA_UPSTREAM_ARTIFACT_METADATA"]) == {
        "k": "v"
    }
