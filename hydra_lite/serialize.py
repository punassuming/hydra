"""Map lite store rows to the main edition's JSON response shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from worker.protocol import WORKER_PROTOCOL_VERSION

from .logs import LogStore


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def run_to_api(run: dict[str, Any], job: Optional[dict], logs: Optional[LogStore] = None, full: bool = True) -> dict[str, Any]:
    start, end = _dt(run.get("start_ts")), _dt(run.get("end_ts"))
    duration = (end - start).total_seconds() if start and end else None
    stdout = stderr = ""
    if full and logs is not None:
        stdout, _ = logs.read(run["id"], "out")
        stderr, _ = logs.read(run["id"], "err")
    executor = ((job or {}).get("executor") or {}).get("type")
    out = {
        "_id": run["id"],
        "id": run["id"],
        "job_id": run["job_id"],
        "job_name": (job or {}).get("name"),
        "user": (job or {}).get("user", "default"),
        "domain": "prod",
        "worker_id": run.get("worker_id"),
        "start_ts": run.get("start_ts"),
        "scheduled_ts": run.get("scheduled_ts"),
        "end_ts": run.get("end_ts"),
        "status": run["status"],
        "trigger": run.get("trigger"),
        "returncode": run.get("returncode"),
        "stdout": stdout,
        "stderr": stderr,
        "attempt": run.get("attempt"),
        "executor_type": executor,
        "queue_latency_ms": run.get("queue_latency_ms"),
        "total_run_ms": run.get("total_run_ms"),
        "completion_reason": run.get("completion_reason"),
        "retry_attempt": run.get("retry_attempt", 0),
        "duration": duration,
        "params": run.get("params") or {},
        # fields defined by the main edition's JobRun that lite has no concept of (kept for shape parity)
        "stdout_tail": stdout[-2000:] if stdout else None,
        "stderr_tail": stderr[-2000:] if stderr else None,
        "slot": None,
        "retries_remaining": None,
        "schedule_tick": run.get("scheduled_ts"),
        "schedule_mode": ((job or {}).get("schedule") or {}).get("mode"),
        "bypass_concurrency": bool((job or {}).get("bypass_concurrency", False)),
        "sla_miss_alerted": bool(run.get("sla_miss_alerted", False)),
    }
    return out


def _csv(value: Any) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in (value or [])]


def worker_to_api(
    worker: dict[str, Any],
    running_jobs: Optional[list[str]] = None,
    running_users: Optional[list[str]] = None,
    heartbeat_ttl: float = 10.0,
) -> dict[str, Any]:
    beat = datetime.fromisoformat(worker["last_heartbeat"])
    age = (datetime.now(timezone.utc) - beat).total_seconds()
    online = age <= heartbeat_ttl
    state = worker["state"]
    running_jobs = running_jobs or []
    meta = worker.get("meta") or {}
    return {
        "os": meta.get("os", ""),
        "hostname": meta.get("hostname"),
        "ip": meta.get("ip"),
        "subnet": meta.get("subnet"),
        "cpu_count": meta.get("cpu_count"),
        "python_version": meta.get("python_version"),
        "cwd": meta.get("cwd"),
        "run_user": meta.get("run_user"),
        "deployment_type": meta.get("deployment_type"),
        "shells": _csv(meta.get("shells")),
        "_id": worker["id"],
        "worker_id": worker["id"],
        "domain": "prod",
        "pid": worker["pid"],
        "status": "online" if online else "offline",
        "state": state,
        "connectivity_status": "online" if online else "offline",
        "dispatch_status": "dispatching" if online and state == "online" else "paused",
        "current_running": len(running_jobs),
        "running_jobs": running_jobs,
        "running_users": running_users or [],
        "max_concurrency": worker["max_concurrency"],
        "tags": worker["tags"],
        "allowed_users": _csv(meta.get("allowed_users")),
        "capabilities": worker["capabilities"],
        "last_heartbeat": beat.timestamp(),
        "heartbeat_age_seconds": round(age, 3),
        "started_at": worker["started_at"],
        "process_count": None,
        "memory_rss_mb": None,
        "load_1m": None,
        "load_5m": None,
        "process_count_max_30m": None,
        "memory_rss_mb_max_30m": None,
        "load_1m_max_30m": None,
        "metrics_updated_at": None,
        "worker_protocol_version": meta.get("worker_protocol_version"),
        "protocol_mismatch": meta.get("worker_protocol_version") != WORKER_PROTOCOL_VERSION,
    }
