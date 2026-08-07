"""Job submission + polling helpers shared by every acceptance test."""

import time
from typing import Optional

from ._client import Client

TERMINAL_STATES = {"success", "failed", "timed_out"}


def submit_job(client: Client, payload: dict) -> dict:
    return client.post("/jobs/", payload)


def wait_for_terminal_run(client: Client, job_id: str, timeout: float, poll_interval: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout
    latest: Optional[dict] = None
    while time.monotonic() < deadline:
        runs = client.get(f"/jobs/{job_id}/runs")
        if runs:
            latest = runs[0]
            if latest.get("status") in TERMINAL_STATES:
                return latest
        time.sleep(poll_interval)
    if latest is None:
        raise AssertionError(f"job {job_id} never produced a run within {timeout}s (no worker picked it up?)")
    raise AssertionError(f"job {job_id} did not reach a terminal state within {timeout}s: {latest}")


def submit_and_wait(client: Client, payload: dict, timeout: float, poll_interval: float = 1.0) -> dict:
    job = submit_job(client, payload)
    job_id = job.get("_id") or job.get("id")
    assert job_id, f"job submission did not return an id: {job}"
    return wait_for_terminal_run(client, job_id, timeout, poll_interval)
