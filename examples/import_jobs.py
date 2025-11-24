"""
Import sample job definitions into the current domain.

Usage:
  API_BASE=http://localhost:8000 API_TOKEN=<domain_or_admin_token> python examples/import_jobs.py

The API token determines the domain (admin token can target any domain if you pass ?domain=<name> manually).
"""

import json
import os
from pathlib import Path
import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_TOKEN = os.getenv("API_TOKEN")
JOBS_DIR = Path(__file__).parent / "jobs"

if not API_TOKEN:
    raise SystemExit("API_TOKEN is required")

HEADERS = {"Content-Type": "application/json", "x-api-key": API_TOKEN}


def import_job(path: Path):
    with path.open() as f:
        payload = json.load(f)
    resp = requests.post(f"{API_BASE}/jobs/", headers=HEADERS, json=payload, timeout=10)
    if resp.status_code >= 400:
        print(f"[fail] {path.name}: {resp.status_code} {resp.text}")
    else:
        print(f"[ok] {path.name}: {resp.json().get('_id', '')}")


def main():
    files = sorted(JOBS_DIR.glob("*.json"))
    if not files:
        print("No job files found in examples/jobs")
        return
    for path in files:
        import_job(path)


if __name__ == "__main__":
    main()
