"""Bounded live acceptance for the OpenClaw Hydra integration.

The runner deliberately creates only disposable domains, workers, and jobs.
It never prints tokens or responses containing them.  It is intended to be
executed where ``HYDRA_API_URL``, ``ADMIN_TOKEN``, ``SEED_DOMAIN`` and
``SEED_DOMAIN_TOKEN`` are already provisioned by the deployment.
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

# Support the documented direct-script form as well as ``python -m``.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.external_client.client import HydraClient, HydraError


def _id(value: dict[str, Any]) -> str:
    return str(value.get("_id") or value.get("id") or value["job_id"])


def _expect(status: int, action, label: str) -> None:
    try:
        action()
    except HydraError as exc:
        if exc.status == status:
            return
        raise AssertionError(f"{label}: expected HTTP {status}, got {exc.status}") from exc
    raise AssertionError(f"{label}: expected HTTP {status}, request succeeded")


def _expect_denied(action, label: str) -> None:
    """A scoped lookup may deliberately hide foreign resources as 404."""
    try:
        action()
    except HydraError as exc:
        if exc.status in {403, 404}:
            return
        raise AssertionError(f"{label}: expected HTTP 403 or 404, got {exc.status}") from exc
    raise AssertionError(f"{label}: request succeeded")


def _terminal(client: HydraClient, job_id: str, timeout: float = 45) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        runs = client.request("GET", f"/jobs/{job_id}/runs") or []
        if runs and runs[0].get("status") in {"success", "failed", "timed_out", "cancelled", "canceled"}:
            return runs[0]
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _running(client: HydraClient, job_id: str, timeout: float = 20) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        runs = client.request("GET", f"/jobs/{job_id}/runs") or []
        if runs and runs[0].get("status") == "running":
            return runs[0]
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not start")


def _job(name: str, script: str, *, timeout: int, retries: int | None = None) -> dict[str, Any]:
    value = {
        "name": name,
        "user": "acceptance",
        "executor": {"type": "shell", "shell": "bash", "script": script},
        "schedule": {"mode": "immediate", "enabled": False},
        "timeout": timeout,
    }
    if retries is not None:
        value["max_retries"] = retries
    return value


def main() -> int:
    base_url = os.environ.get("HYDRA_API_URL", "http://127.0.0.1:8000")
    admin_token = os.environ["ADMIN_TOKEN"]
    seed_domain = os.environ["SEED_DOMAIN"]
    seed_token = os.environ["SEED_DOMAIN_TOKEN"]
    admin = HydraClient(base_url, admin_token, "admin")
    suffix = secrets.token_hex(4)
    a_name, b_name = f"openclaw-a-{suffix}", f"openclaw-b-{suffix}"
    created: list[str] = []
    report: list[str] = []
    try:
        a = admin.request("POST", "/admin/domains", {"domain": a_name, "display_name": "OpenClaw acceptance A"})
        b = admin.request("POST", "/admin/domains", {"domain": b_name, "display_name": "OpenClaw acceptance B"})
        created.extend([a_name, b_name])
        a_client, b_client = HydraClient(base_url, a["token"], a_name), HydraClient(base_url, b["token"], b_name)
        a_job = a_client.submit(_job(f"openclaw-isolation-{suffix}", "true", timeout=10))
        a_job_id = _id(a_job)
        _expect(403, lambda: b_client.request("GET", f"/jobs/{a_job_id}"), "B read A job")
        _expect(403, lambda: b_client.run(a_job_id), "B submit A job")
        if any(_id(item) == a_job_id for item in b_client.request("GET", "/jobs/")):
            raise AssertionError("B job listing exposed A job")
        if any(item.get("domain") == a_name for item in b_client.history()):
            raise AssertionError("B history exposed A history")
        report.append("two-domain job/list/history isolation")

        rotated = a_client.rotate_token()
        new_a = HydraClient(base_url, rotated["token"], a_name)
        _expect(401, lambda: a_client.history(), "old A token after rotation")
        new_a.history()
        admin.request("DELETE", f"/admin/domains/{a_name}")
        created.remove(a_name)
        _expect(401, lambda: new_a.history(), "new A token after revocation")
        report.append("rotation immediate rejection and domain-token revocation")

        live = HydraClient(base_url, seed_token, seed_domain)
        echo = _job(f"openclaw-echo-{suffix}", "printf 'openclaw-acceptance\\n'", timeout=10, retries=1)
        if not live.validate(echo).get("valid"):
            raise AssertionError("echo validation failed")
        echo_id = _id(live.submit(echo))
        live.run(echo_id)
        echo_run = _terminal(live, echo_id)
        if echo_run.get("status") != "success":
            raise AssertionError(f"echo status was {echo_run.get('status')}")
        run_id = str(echo_run.get("_id") or echo_run.get("id"))
        if not live.logs(run_id):
            raise AssertionError("echo log record was empty")
        if not any(str(item.get("_id") or item.get("id")) == run_id for item in live.history()):
            raise AssertionError("echo run missing from history")
        _expect(403, lambda: b_client.logs(run_id), "B access seed-domain logs")
        report.append("validate-submit-run-logs-history")

        cancel_id = _id(live.submit(_job(f"openclaw-cancel-{suffix}", "sleep 30", timeout=45)))
        live.run(cancel_id)
        cancel_run = _running(live, cancel_id)
        cancel_run_id = str(cancel_run.get("_id") or cancel_run.get("id"))
        _expect_denied(lambda: b_client.cancel(cancel_run_id), "B cancel seed-domain run")
        live.cancel(cancel_run_id)
        cancelled = _terminal(live, cancel_id, timeout=25)
        if cancelled.get("status") not in {"failed", "cancelled", "canceled"}:
            raise AssertionError(f"cancellation status was {cancelled.get('status')}")
        report.append("distinct long-running cancellation")

        timeout_id = _id(live.submit(_job(f"openclaw-timeout-{suffix}", "sleep 2", timeout=1)))
        live.run(timeout_id)
        timed = _terminal(live, timeout_id)
        if timed.get("status") != "timed_out":
            raise AssertionError(f"timeout status was {timed.get('status')}")
        retry_id = _id(live.submit(_job(f"openclaw-retry-{suffix}", "exit 1", timeout=10, retries=1)))
        live.run(retry_id)
        retried = _terminal(live, retry_id)
        if retried.get("status") != "failed":
            raise AssertionError(f"retry job status was {retried.get('status')}")
        report.append("timeout and retry terminal handling")
        print("PASS: " + "; ".join(report))
        return 0
    finally:
        for domain in created:
            try:
                admin.request("DELETE", f"/admin/domains/{domain}")
            except HydraError:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
