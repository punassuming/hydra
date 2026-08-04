"""Canned operational investigations — the "smart investigation tool".

Deliberately LLM-free: every investigation here is a fixed, whitelisted query
compiled by hand, not a prompt interpreted by a model. That keeps results
fast, free (no provider API key required), and fully deterministic, at the
cost of only covering the questions we've hard-coded below. The AI-diagnosis
features in `scheduler/api/ai.py` are the complement to this — reach for
those when you need a specific run explained, reach for this when you want a
quick "what needs attention right now" sweep across all jobs.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from ..mongo_client import get_db
from .ai import MAX_PREDICTION_SAMPLE_SIZE, duration_percentiles

router = APIRouter(prefix="/investigations", tags=["Investigations"])

FLAKY_SAMPLE_SIZE = 10
FLAKY_MIN_FAILURE_RATE = 0.2
FLAKY_MAX_FAILURE_RATE = 0.8
NEVER_SUCCEEDED_MIN_RUNS = 3
LONG_RUNNING_MULTIPLIER = 2.0
DEFAULT_RECENT_HOURS = 24

_CATALOG = [
    {
        "key": "failed_recent",
        "label": "Recently Failed",
        "description": "Jobs with at least one failed or timed-out run in the last 24 hours.",
    },
    {
        "key": "long_running_outliers",
        "label": "Running Longer Than Usual",
        "description": "In-progress runs that have already exceeded 2x their job's typical (p90) duration.",
    },
    {
        "key": "flaky_jobs",
        "label": "Flaky Jobs",
        "description": f"Jobs whose last {FLAKY_SAMPLE_SIZE} runs mix successes and failures.",
    },
    {
        "key": "never_succeeded",
        "label": "Never Succeeded",
        "description": f"Jobs with at least {NEVER_SUCCEEDED_MIN_RUNS} runs where none have succeeded.",
    },
]
_CATALOG_BY_KEY = {item["key"]: item for item in _CATALOG}


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _scope_query(request: Request) -> dict:
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    if is_admin and force_domain:
        return {"domain": force_domain}
    if is_admin:
        return {}
    return {"domain": domain}


def _investigate_failed_recent(db, jobs: list, hours: float) -> list:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    results = []
    for job in jobs:
        job_id = job["_id"]
        runs = list(
            db.job_runs.find(
                {"job_id": job_id, "status": {"$in": ["failed", "timed_out"]}, "start_ts": {"$gte": since}}
            ).sort("start_ts", -1)
        )
        if not runs:
            continue
        latest = runs[0]
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": "failures in window",
                "metric_value": len(runs),
                "last_run_id": latest.get("_id"),
                "last_run_at": _iso(latest.get("start_ts")),
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _investigate_long_running(db, jobs: list) -> list:
    now = datetime.now(timezone.utc)
    results = []
    for job in jobs:
        job_id = job["_id"]
        running = list(db.job_runs.find({"job_id": job_id, "status": "running"}))
        if not running:
            continue
        stats = duration_percentiles(db, job_id, job.get("domain"), MAX_PREDICTION_SAMPLE_SIZE)
        if not stats or not stats["p90_seconds"]:
            continue
        threshold = stats["p90_seconds"] * LONG_RUNNING_MULTIPLIER
        for run in running:
            start_ts = run.get("start_ts")
            if not start_ts:
                continue
            elapsed = (now - start_ts).total_seconds()
            if elapsed < threshold:
                continue
            results.append(
                {
                    "job_id": job_id,
                    "job_name": job.get("name", job_id),
                    "domain": job.get("domain", "prod"),
                    "metric_label": "elapsed vs p90 baseline",
                    "metric_value": round(elapsed / stats["p90_seconds"], 1),
                    "last_run_id": run.get("_id"),
                    "last_run_at": _iso(start_ts),
                }
            )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _investigate_flaky(db, jobs: list) -> list:
    results = []
    for job in jobs:
        job_id = job["_id"]
        runs = list(
            db.job_runs.find({"job_id": job_id, "status": {"$in": ["success", "failed", "timed_out"]}})
            .sort("start_ts", -1)
            .limit(FLAKY_SAMPLE_SIZE)
        )
        if len(runs) < FLAKY_SAMPLE_SIZE:
            continue
        failures = sum(1 for r in runs if r.get("status") in ("failed", "timed_out"))
        failure_rate = failures / len(runs)
        if not (FLAKY_MIN_FAILURE_RATE <= failure_rate <= FLAKY_MAX_FAILURE_RATE):
            continue
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": f"failure rate, last {FLAKY_SAMPLE_SIZE} runs",
                "metric_value": round(failure_rate * 100),
                "last_run_id": runs[0].get("_id"),
                "last_run_at": _iso(runs[0].get("start_ts")),
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _investigate_never_succeeded(db, jobs: list) -> list:
    results = []
    for job in jobs:
        job_id = job["_id"]
        total = db.job_runs.count_documents({"job_id": job_id, "status": {"$in": ["success", "failed", "timed_out"]}})
        if total < NEVER_SUCCEEDED_MIN_RUNS:
            continue
        successes = db.job_runs.count_documents({"job_id": job_id, "status": "success"})
        if successes > 0:
            continue
        latest = next(iter(db.job_runs.find({"job_id": job_id}).sort("start_ts", -1).limit(1)), None)
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": "runs with zero successes",
                "metric_value": total,
                "last_run_id": latest.get("_id") if latest else None,
                "last_run_at": _iso(latest.get("start_ts")) if latest else None,
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


@router.get("/")
def list_investigations():
    return _CATALOG


@router.get("/{key}")
def run_investigation(key: str, request: Request):
    if key not in _CATALOG_BY_KEY:
        raise HTTPException(status_code=404, detail="unknown investigation")

    db = get_db()
    jobs = list(db.job_definitions.find(_scope_query(request), {"name": 1, "domain": 1}))

    if key == "failed_recent":
        try:
            hours = float(request.query_params.get("hours", DEFAULT_RECENT_HOURS))
        except ValueError:
            hours = DEFAULT_RECENT_HOURS
        results = _investigate_failed_recent(db, jobs, hours)
    elif key == "long_running_outliers":
        results = _investigate_long_running(db, jobs)
    elif key == "flaky_jobs":
        results = _investigate_flaky(db, jobs)
    else:
        results = _investigate_never_succeeded(db, jobs)

    return {"key": key, "label": _CATALOG_BY_KEY[key]["label"], "results": results}
