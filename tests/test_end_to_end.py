"""Service-backed smoke test for the complete Hydra job lifecycle."""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

E2E_ENABLED = os.getenv("HYDRA_E2E", "").lower() in {"1", "true", "yes"}
API_BASE = os.getenv("HYDRA_E2E_URL", "http://127.0.0.1:8000").rstrip("/")
DOMAIN = os.getenv("HYDRA_E2E_DOMAIN", "ci")
TOKEN = os.getenv("HYDRA_E2E_TOKEN", "ci-domain-token")


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "x-api-key": TOKEN,
            "x-domain": DOMAIN,
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def _wait_for_api(timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{API_BASE}/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"scheduler did not become healthy: {last_error}")


@pytest.mark.skipif(not E2E_ENABLED, reason="set HYDRA_E2E=1 and start the Compose test stack")
def test_shell_job_completes_through_full_stack():
    _wait_for_api()
    job = _request(
        "POST",
        "/jobs/",
        {
            "name": f"ci-smoke-{time.time_ns()}",
            "user": "ci",
            "executor": {
                "type": "shell",
                "shell": "bash",
                "script": "echo hydra-e2e-ok",
            },
            "timeout": 30,
        },
    )
    job_id = job.get("_id") or job.get("id")
    assert job_id, job

    deadline = time.monotonic() + 90
    latest_run: dict | None = None
    while time.monotonic() < deadline:
        runs = _request("GET", f"/jobs/{job_id}/runs")
        if runs:
            latest_run = runs[0]
            if latest_run.get("status") in {"success", "failed", "timed_out"}:
                break
        time.sleep(1)

    assert latest_run is not None, "worker never emitted a run event"
    assert latest_run.get("status") == "success", latest_run
    output = f"{latest_run.get('stdout', '')}\n{latest_run.get('stdout_tail', '')}"
    assert "hydra-e2e-ok" in output
