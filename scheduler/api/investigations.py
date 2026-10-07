"""Canned operational investigations — the "smart investigation tool".

Deliberately LLM-free: every investigation here is a fixed, whitelisted query
compiled by hand, not a prompt interpreted by a model. That keeps results
fast, free (no provider API key required), and fully deterministic, at the
cost of only covering the questions we've hard-coded below. The AI-diagnosis
features in `scheduler/api/ai.py` are the complement to this — reach for
those when you need a specific run explained, reach for this when you want a
quick "what needs attention right now" sweep across all jobs.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from ..mongo_client import get_db
from ..redis_client import get_redis
from .ai import MAX_PREDICTION_SAMPLE_SIZE, duration_percentiles

router = APIRouter(prefix="/investigations", tags=["Investigations"])

FLAKY_SAMPLE_SIZE = 10
FLAKY_MIN_FAILURE_RATE = 0.2
FLAKY_MAX_FAILURE_RATE = 0.8
NEVER_SUCCEEDED_MIN_RUNS = 3
LONG_RUNNING_MULTIPLIER = 2.0
DEFAULT_RECENT_HOURS = 24
SLA_MISS_LOOKBACK_HOURS = 24
RETRY_STORM_LOOKBACK_HOURS = 24
RETRY_STORM_MIN_COUNT = 3
# A cron/interval job whose next_run_at is this far in the past isn't being
# triggered: schedule_trigger_loop advances next_run_at the moment it enqueues,
# so a stale value means the orchestrator is down or wedged.
SCHEDULE_OVERDUE_GRACE_SECONDS = 300

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
    {
        "key": "sla_miss",
        "label": "SLA Misses",
        "description": (
            f"Jobs with a running or recently-completed run exceeding its "
            f"sla_max_duration_seconds, in the last {SLA_MISS_LOOKBACK_HOURS}h."
        ),
    },
    {
        "key": "retry_storm",
        "label": "Retry Storms",
        "description": (
            f"Jobs with at least {RETRY_STORM_MIN_COUNT} scheduler-retried runs "
            f"in the last {RETRY_STORM_LOOKBACK_HOURS}h."
        ),
    },
    {
        "key": "dead_letter",
        "label": "Dead Letter",
        "description": (
            "Jobs configured with retries whose most recent run failed or timed out "
            "after exhausting every configured retry attempt."
        ),
    },
    {
        "key": "queue_starvation",
        "label": "Queue Starvation",
        "description": (
            "Pending jobs that have been requeued repeatedly because no eligible worker "
            "exists (at or above SCHEDULER_STARVATION_WARN_THRESHOLD misses)."
        ),
    },
    {
        "key": "worker_offline",
        "label": "Offline Workers",
        "description": (
            "Registered workers whose heartbeat has lapsed and that were not deliberately "
            "set offline by an operator."
        ),
    },
    {
        "key": "schedule_overdue",
        "label": "Overdue Schedules",
        "description": (
            f"Enabled cron/interval jobs whose next run is more than "
            f"{SCHEDULE_OVERDUE_GRACE_SECONDS // 60} minutes in the past, meaning the "
            "scheduler is not triggering them."
        ),
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


def _investigate_sla_miss(db, jobs: list) -> list:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=SLA_MISS_LOOKBACK_HOURS)
    results = []
    for job in jobs:
        job_id = job["_id"]
        sla_seconds = job.get("sla_max_duration_seconds")
        try:
            sla_seconds = int(sla_seconds) if sla_seconds is not None else 0
        except (TypeError, ValueError):
            continue
        if sla_seconds <= 0:
            continue
        runs = list(
            db.job_runs.find(
                {
                    "job_id": job_id,
                    "status": {"$in": ["running", "success", "failed", "timed_out"]},
                    "start_ts": {"$gte": since},
                }
            ).sort("start_ts", -1)
        )
        worst_run = None
        worst_overage = 0.0
        for run in runs:
            start_ts = run.get("start_ts")
            if not start_ts:
                continue
            if run.get("status") == "running":
                duration = (now - start_ts).total_seconds()
            else:
                duration = run.get("duration")
                if not isinstance(duration, (int, float)):
                    continue
            overage = duration - sla_seconds
            if overage > worst_overage:
                worst_overage = overage
                worst_run = run
        if worst_run is None:
            continue
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": f"seconds over {sla_seconds}s SLA",
                "metric_value": round(worst_overage, 1),
                "last_run_id": worst_run.get("_id"),
                "last_run_at": _iso(worst_run.get("start_ts")),
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _investigate_retry_storm(db, jobs: list) -> list:
    since = datetime.now(timezone.utc) - timedelta(hours=RETRY_STORM_LOOKBACK_HOURS)
    results = []
    for job in jobs:
        job_id = job["_id"]
        runs = list(
            db.job_runs.find(
                {"job_id": job_id, "retry_attempt": {"$gt": 0}, "start_ts": {"$gte": since}}
            ).sort("start_ts", -1)
        )
        if len(runs) < RETRY_STORM_MIN_COUNT:
            continue
        latest = runs[0]
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": f"retried runs in last {RETRY_STORM_LOOKBACK_HOURS}h",
                "metric_value": len(runs),
                "last_run_id": latest.get("_id"),
                "last_run_at": _iso(latest.get("start_ts")),
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _investigate_dead_letter(db, jobs: list) -> list:
    """Jobs configured with scheduler-level retries whose most recent run
    genuinely gave up (failed/timed out after retry_attempt reached
    max_retries) — distinct from retry_storm, which flags jobs still
    actively retry-looping, not ones that have stopped retrying entirely.
    """
    results = []
    for job in jobs:
        job_id = job["_id"]
        max_retries = job.get("max_retries")
        try:
            max_retries = int(max_retries) if max_retries is not None else 0
        except (TypeError, ValueError):
            continue
        if max_retries <= 0:
            continue
        latest = next(iter(db.job_runs.find({"job_id": job_id}).sort("start_ts", -1).limit(1)), None)
        if not latest or latest.get("status") not in ("failed", "timed_out"):
            continue
        retry_attempt = latest.get("retry_attempt")
        try:
            retry_attempt = int(retry_attempt) if retry_attempt is not None else 0
        except (TypeError, ValueError):
            retry_attempt = 0
        if retry_attempt < max_retries:
            continue
        results.append(
            {
                "job_id": job_id,
                "job_name": job.get("name", job_id),
                "domain": job.get("domain", "prod"),
                "metric_label": f"retry attempts exhausted (max {max_retries})",
                "metric_value": retry_attempt,
                "last_run_id": latest.get("_id"),
                "last_run_at": _iso(latest.get("start_ts")),
            }
        )
    results.sort(key=lambda r: r["metric_value"], reverse=True)
    return results


def _as_utc(value: Any) -> Optional[datetime]:
    """Coerce a stored timestamp (datetime or ISO string) to an aware UTC datetime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _investigate_queue_starvation(r, jobs: list) -> list:
    """Jobs sitting in a domain's pending queue that the scheduler keeps
    requeueing because no worker is eligible (job_enqueue_meta.no_worker_count,
    maintained by the scheduling loop)."""
    threshold = int(os.getenv("SCHEDULER_STARVATION_WARN_THRESHOLD", "5"))
    by_domain: dict = {}
    for job in jobs:
        by_domain.setdefault(job.get("domain", "prod"), {})[job["_id"]] = job
    results = []
    for domain, domain_jobs in by_domain.items():
        for job_id in r.zrange(f"job_queue:{domain}:pending", 0, -1):
            job = domain_jobs.get(job_id)
            if job is None:
                continue
            meta = r.hgetall(f"job_enqueue_meta:{domain}:{job_id}") or {}
            try:
                misses = int(meta.get("no_worker_count", 0))
            except (TypeError, ValueError):
                continue
            if misses < threshold:
                continue
            enqueued = meta.get("enqueued_ts")
            try:
                enqueued_iso = datetime.fromtimestamp(float(enqueued), tz=timezone.utc).isoformat()
            except (TypeError, ValueError):
                enqueued_iso = None
            results.append(
                {
                    "job_id": job_id,
                    "job_name": job.get("name", job_id),
                    "domain": domain,
                    "metric_label": "scheduling attempts with no eligible worker",
                    "metric_value": misses,
                    "last_run_id": None,
                    "last_run_at": enqueued_iso,
                }
            )
    results.sort(key=lambda row: row["metric_value"], reverse=True)
    return results


def _investigate_worker_offline(r, domains: list) -> list:
    """Workers that registered but stopped heartbeating. Workers an operator
    set to offline on purpose are excluded (that's intent, not an incident).
    Rows use entity="worker": job_id/job_name carry the worker id."""
    ttl = max(2, int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10")))
    now = datetime.now(timezone.utc).timestamp()
    results = []
    for domain in domains:
        for key in r.scan_iter(f"workers:{domain}:*"):
            worker_id = key.split(":", 2)[2] if key.count(":") >= 2 else key
            data = r.hgetall(key) or {}
            if str(data.get("state", "online")).lower() in ("offline", "disabled"):
                continue
            heartbeat = r.zscore(f"worker_heartbeats:{domain}", worker_id)
            if heartbeat is None or now - float(heartbeat) <= ttl:
                continue
            results.append(
                {
                    "entity": "worker",
                    "job_id": worker_id,
                    "job_name": data.get("hostname") or worker_id,
                    "domain": domain,
                    "metric_label": "seconds since last heartbeat",
                    "metric_value": round(now - float(heartbeat)),
                    "last_run_id": None,
                    "last_run_at": datetime.fromtimestamp(float(heartbeat), tz=timezone.utc).isoformat(),
                }
            )
    results.sort(key=lambda row: row["metric_value"], reverse=True)
    return results


def _investigate_schedule_overdue(jobs: list) -> list:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=SCHEDULE_OVERDUE_GRACE_SECONDS)
    results = []
    for job in jobs:
        schedule = job.get("schedule") or {}
        if not schedule.get("enabled") or schedule.get("mode") not in ("cron", "interval"):
            continue
        next_run = _as_utc(schedule.get("next_run_at"))
        if next_run is None or next_run >= cutoff:
            continue
        end_at = _as_utc(schedule.get("end_at"))
        if end_at is not None and end_at <= now:
            continue  # window has closed; not being triggered is expected
        results.append(
            {
                "job_id": job["_id"],
                "job_name": job.get("name", job["_id"]),
                "domain": job.get("domain", "prod"),
                "metric_label": "minutes overdue",
                "metric_value": round((now - next_run).total_seconds() / 60, 1),
                "last_run_id": None,
                "last_run_at": _iso(next_run),
            }
        )
    results.sort(key=lambda row: row["metric_value"], reverse=True)
    return results


@router.get("/")
def list_investigations():
    return _CATALOG


@router.get("/{key}")
def run_investigation(key: str, request: Request):
    if key not in _CATALOG_BY_KEY:
        raise HTTPException(status_code=404, detail="unknown investigation")

    db = get_db()
    jobs = list(
        db.job_definitions.find(
            _scope_query(request),
            {"name": 1, "domain": 1, "sla_max_duration_seconds": 1, "max_retries": 1, "schedule": 1},
        )
    )

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
    elif key == "never_succeeded":
        results = _investigate_never_succeeded(db, jobs)
    elif key == "sla_miss":
        results = _investigate_sla_miss(db, jobs)
    elif key == "retry_storm":
        results = _investigate_retry_storm(db, jobs)
    elif key == "queue_starvation":
        results = _investigate_queue_starvation(get_redis(), jobs)
    elif key == "worker_offline":
        scope = _scope_query(request)
        if "domain" in scope:
            domains = [scope["domain"]]
        else:
            r = get_redis()
            domains = sorted({k.split(":")[1] for k in r.scan_iter("workers:*") if k.count(":") >= 2})
        results = _investigate_worker_offline(get_redis(), domains)
    elif key == "schedule_overdue":
        results = _investigate_schedule_overdue(jobs)
    else:
        results = _investigate_dead_letter(db, jobs)

    return {"key": key, "label": _CATALOG_BY_KEY[key]["label"], "results": results}
