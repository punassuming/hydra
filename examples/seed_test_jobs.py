"""
Seed a handful of smoke-test jobs to exercise Hydra’s schedulers/workers.

Requirements:
  pip install requests

Usage:
  API_BASE=http://localhost:8000 API_TOKEN=changeme python examples/seed_test_jobs.py
"""

import os
import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_TOKEN = os.getenv("API_TOKEN")

HEADERS = {"Content-Type": "application/json"}
if API_TOKEN:
    HEADERS["x-api-key"] = API_TOKEN


def post(path: str, payload: dict):
    url = f"{API_BASE}{path}"
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    print(f"[ok] {path} -> {resp.json().get('_id', resp.text)}")


def main():
    jobs = [
        {
          "name": "smoke-shell-quick",
          "user": "smoke",
          "queue": "default",
          "priority": 5,
          "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
          "executor": {"type": "shell", "shell": "bash", "script": "echo quick ok"},
          "retries": 0,
          "timeout": 30,
          "schedule": {"mode": "immediate", "enabled": True},
          "completion": {"exit_codes": [0], "stdout_contains": [], "stdout_not_contains": [], "stderr_contains": [], "stderr_not_contains": []}
        },
        {
          "name": "smoke-shell-long",
          "user": "smoke",
          "queue": "default",
          "priority": 4,
          "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
          "executor": {"type": "shell", "shell": "bash", "script": "echo start; sleep 10; echo done"},
          "retries": 0,
          "timeout": 120,
          "schedule": {"mode": "immediate", "enabled": True},
          "completion": {"exit_codes": [0], "stdout_contains": ["done"], "stdout_not_contains": [], "stderr_contains": [], "stderr_not_contains": []}
        },
        {
          "name": "smoke-failing",
          "user": "smoke",
          "queue": "default",
          "priority": 3,
          "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
          "executor": {"type": "shell", "shell": "bash", "script": "echo boom >&2; exit 42"},
          "retries": 0,
          "timeout": 30,
          "schedule": {"mode": "immediate", "enabled": True},
          "completion": {"exit_codes": [0], "stdout_contains": [], "stdout_not_contains": [], "stderr_contains": [], "stderr_not_contains": []}
        },
        {
          "name": "smoke-python",
          "user": "smoke",
          "queue": "default",
          "priority": 5,
          "affinity": {"os": ["linux"], "tags": ["python"], "allowed_users": []},
          "executor": {
            "type": "python",
            "interpreter": "python3",
            "code": "import time; print('tick'); time.sleep(2); print('tock')",
            "environment": {"type": "system", "python_version": "python3", "requirements": []}
          },
          "retries": 0,
          "timeout": 60,
          "schedule": {"mode": "immediate", "enabled": True},
          "completion": {"exit_codes": [0], "stdout_contains": ["tock"], "stdout_not_contains": [], "stderr_contains": [], "stderr_not_contains": []}
        },
        {
          "name": "smoke-cron",
          "user": "smoke",
          "queue": "default",
          "priority": 2,
          "affinity": {"os": ["linux"], "tags": [], "allowed_users": []},
          "executor": {"type": "shell", "shell": "bash", "script": "echo cron-run $(date +%s)"},
          "retries": 0,
          "timeout": 30,
          "schedule": {"mode": "cron", "cron": "*/5 * * * *", "enabled": True},
          "completion": {"exit_codes": [0], "stdout_contains": [], "stdout_not_contains": [], "stderr_contains": [], "stderr_not_contains": []}
        },
    ]
    for job in jobs:
        post("/jobs/", job)


if __name__ == "__main__":
    main()
