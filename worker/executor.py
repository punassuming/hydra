from datetime import datetime
from typing import Tuple

from bson import ObjectId

from .mongo_client import get_db
from .utils.os_exec import run_command, run_python, run_external


def execute_job(job: dict) -> Tuple[int, str, str]:
    executor = job.get("executor") or {}
    timeout = job.get("timeout", 0) or None
    env = executor.get("env")
    workdir = executor.get("workdir")
    args = executor.get("args") or []
    exec_type = (executor.get("type") or job.get("shell") or "shell").lower()

    if exec_type == "python":
        code = executor.get("code") or job.get("command", "")
        interpreter = executor.get("interpreter", "python3")
        return run_python(code=code, interpreter=interpreter, args=args, timeout=timeout, env=env, workdir=workdir)
    if exec_type == "external":
        binary = executor.get("command") or job.get("command", "")
        return run_external(binary=binary, args=args, timeout=timeout, env=env, workdir=workdir)
    if exec_type == "batch":
        script = executor.get("script") or job.get("command", "")
        shell = executor.get("shell", "cmd")
        return run_command(script, shell=shell, timeout=timeout, env=env, workdir=workdir)

    # default shell executor
    script = executor.get("script") or job.get("command", "")
    shell = executor.get("shell", job.get("shell", "bash"))
    return run_command(script, shell=shell, timeout=timeout, env=env, workdir=workdir)


def record_run_start(job: dict, worker_id: str, slot: int, retries_remaining: int) -> str:
    db = get_db()
    job_id = job.get("_id") or job.get("id")
    user = job.get("user", "")
    executor_type = (job.get("executor") or {}).get("type", "shell")
    created_at = job.get("created_at")
    queue_latency_ms = None
    if created_at:
        try:
            queue_latency_ms = max(0.0, (datetime.utcnow() - created_at).total_seconds() * 1000)
        except Exception:
            queue_latency_ms = None
    schedule_info = job.get("schedule") or {}
    run_doc = {
        "job_id": job_id,
        "user": user,
        "worker_id": worker_id,
        "start_ts": datetime.utcnow(),
        "scheduled_ts": datetime.utcnow(),
        "end_ts": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "slot": slot,
        "attempt": 1,
        "retries_remaining": retries_remaining,
        "schedule_tick": schedule_info.get("next_run_at"),
        "schedule_mode": schedule_info.get("mode", "immediate"),
        "executor_type": executor_type,
        "queue_latency_ms": queue_latency_ms,
        "completion_reason": None,
    }
    res = db.job_runs.insert_one(run_doc)
    return str(res.inserted_id)


def record_run_end(run_id: str, status: str, returncode: int, stdout: str, stderr: str, attempts: int, completion_reason: str):
    db = get_db()
    db.job_runs.update_one(
        {"_id": ObjectId(run_id)},
        {
            "$set": {
                "end_ts": datetime.utcnow(),
                "status": status,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "attempt": attempts,
                "completion_reason": completion_reason,
            }
        },
    )
