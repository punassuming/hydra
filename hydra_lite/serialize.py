"""Map lite store rows to the main edition's JSON response shapes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .logs import LogStore

# Lite keeps richer terminal states; the shared shape (and hydra-ctl's wait loops) only know these.
_STATUS = {
    "queued": "pending",
    "dispatched": "dispatched",
    "running": "running",
    "success": "success",
    "failed": "failed",
    "timed_out": "timed_out",
    "killed": "failed",
    "lost": "failed",
    "skipped": "success",
}


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def run_to_api(run: dict[str, Any], job: Optional[dict], logs: Optional[LogStore] = None, full: bool = True) -> dict[str, Any]:
    start, end = _dt(run.get("started_at")), _dt(run.get("finished_at"))
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
        "start_ts": run.get("started_at"),
        "scheduled_ts": run.get("scheduled_for"),
        "end_ts": run.get("finished_at"),
        "status": _STATUS.get(run["status"], run["status"]),
        "detail_status": run["status"],
        "trigger": run.get("trigger"),
        "returncode": run.get("exit_code"),
        "stdout": stdout,
        "stderr": stderr,
        "attempt": run.get("attempt"),
        "executor_type": executor,
        "queue_latency_ms": run.get("queue_latency_ms"),
        "total_run_ms": run.get("total_run_ms"),
        "completion_reason": run.get("reason"),
        "duration": duration,
        "params": run.get("params") or {},
    }
    return out


def worker_to_api(worker: dict[str, Any], running: int = 0, heartbeat_ttl: float = 10.0) -> dict[str, Any]:
    beat = datetime.fromisoformat(worker["last_heartbeat"])
    age = (datetime.now(timezone.utc) - beat).total_seconds()
    online = age <= heartbeat_ttl
    state = worker["state"]
    return {
        "_id": worker["id"],
        "worker_id": worker["id"],
        "domain": "prod",
        "pid": worker["pid"],
        "state": state,
        "connectivity_status": "online" if online else "offline",
        "dispatch_status": "dispatching" if online and state == "online" else "paused",
        "current_running": running,
        "max_concurrency": worker["max_concurrency"],
        "tags": worker["tags"],
        "capabilities": worker["capabilities"],
        "last_heartbeat": worker["last_heartbeat"],
        "started_at": worker["started_at"],
        "worker_protocol_version": None,
        "protocol_mismatch": False,
    }
