"""Map lite store rows to the main edition's JSON response shapes."""

from __future__ import annotations

import getpass
import os
import platform
import socket
from datetime import datetime, timezone
from typing import Any, Optional

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


def _host_info() -> dict[str, Any]:
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "127.0.0.1"
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    return {
        "os": platform.system().lower(),
        "hostname": socket.gethostname(),
        "ip": ip,
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
        "run_user": user,
        "deployment_type": "standalone",
        "shells": [],
    }


_HOST = _host_info()


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
    return {
        **_HOST,
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
        "allowed_users": [],
        "capabilities": worker["capabilities"],
        "last_heartbeat": beat.timestamp(),
        "heartbeat_age_seconds": round(age, 3),
        "started_at": worker["started_at"],
        "subnet": None,
        "process_count": None,
        "memory_rss_mb": None,
        "load_1m": None,
        "load_5m": None,
        "process_count_max_30m": None,
        "memory_rss_mb_max_30m": None,
        "load_1m_max_30m": None,
        "metrics_updated_at": None,
        "worker_protocol_version": None,
        "protocol_mismatch": False,
    }
