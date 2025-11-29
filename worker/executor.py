from datetime import datetime
from typing import Tuple, Callable, Optional
import tempfile
import shutil
import os

from bson import ObjectId

from .mongo_client import get_db
from .utils.os_exec import run_command, run_external, _run_with_callbacks
from .utils.python_env import prepare_python_command
from .utils.git import fetch_git_source


def execute_job(
    job: dict,
    log_callback_out: Optional[Callable[[str], None]] = None,
    log_callback_err: Optional[Callable[[str], None]] = None,
) -> Tuple[int, str, str]:
    executor = job.get("executor") or {}
    timeout = job.get("timeout", 0) or None
    env = executor.get("env")
    workdir = executor.get("workdir")
    args = executor.get("args") or []
    exec_type = (executor.get("type") or job.get("shell") or "shell").lower()
    job_identifier = job.get("_id") or job.get("id") or "job"

    source = job.get("source")
    source_cleanup = None

    if source and source.get("url"):
        tmp_source_dir = tempfile.mkdtemp(prefix=f"hydra-source-{job_identifier}-")
        try:
            fetch_git_source(source["url"], source.get("ref", "main"), tmp_source_dir)
            # Determine effective workdir
            # 1. Start at repo root
            base_path = tmp_source_dir
            # 2. If source has a 'path' sub-directory, append it
            if source.get("path"):
                base_path = os.path.join(base_path, source["path"])
            
            # 3. If executor has a workdir:
            #    - if absolute, use it (ignores repo, risky but standard behavior)
            #    - if relative, append to base_path
            if workdir:
                if os.path.isabs(workdir):
                    pass # keep as is
                else:
                    workdir = os.path.join(base_path, workdir)
            else:
                workdir = base_path
            
            def _cleanup_source():
                shutil.rmtree(tmp_source_dir, ignore_errors=True)
            source_cleanup = _cleanup_source

        except Exception as e:
            shutil.rmtree(tmp_source_dir, ignore_errors=True)
            return 1, "", f"Failed to fetch source: {str(e)}"

    try:
        if exec_type == "python":
            code = executor.get("code") or job.get("command", "")
            try:
                command, cleanup = prepare_python_command(executor, job_identifier)
            except Exception as prep_err:
                return 1, "", str(prep_err)
            try:
                cmd_with_code = command + ["-c", code] + args
                if log_callback_out or log_callback_err:
                    rc, out, err = _run_with_callbacks(
                        cmd_with_code, timeout, env, workdir, on_stdout=log_callback_out, on_stderr=log_callback_err
                    )
                else:
                    rc, out, err = run_external(binary=cmd_with_code[0], args=cmd_with_code[1:], timeout=timeout, env=env, workdir=workdir)
                return rc, out, err
            finally:
                if cleanup:
                    cleanup()
        if exec_type == "external":
            binary = executor.get("command") or job.get("command", "")
            if log_callback_out or log_callback_err:
                cmd = [binary] + args
                return _run_with_callbacks(cmd, timeout, env, workdir, on_stdout=log_callback_out, on_stderr=log_callback_err)
            return run_external(binary=binary, args=args, timeout=timeout, env=env, workdir=workdir)
        if exec_type == "batch":
            script = executor.get("script") or job.get("command", "")
            shell = executor.get("shell", "cmd")
            if log_callback_out or log_callback_err:
                cmd = ["cmd", "/c", script] if shell == "cmd" else [shell, "-c", script]
                return _run_with_callbacks(cmd, timeout, env, workdir, on_stdout=log_callback_out, on_stderr=log_callback_err)
            return run_command(script, shell=shell, timeout=timeout, env=env, workdir=workdir)

        # default shell executor
        script = executor.get("script") or job.get("command", "")
        shell = executor.get("shell", job.get("shell", "bash"))
        cmd = ["/bin/bash", "-lc", script] if shell == "bash" else [shell, "-c", script]
        if log_callback_out or log_callback_err:
            return _run_with_callbacks(cmd, timeout, env, workdir, on_stdout=log_callback_out, on_stderr=log_callback_err)
        return run_command(script, shell=shell, timeout=timeout, env=env, workdir=workdir)
    finally:
        if source_cleanup:
            source_cleanup()


def record_run_start(job: dict, worker_id: str, slot: int, retries_remaining: int) -> str:
    db = get_db()
    job_id = job.get("_id") or job.get("id")
    user = job.get("user", "")
    domain = job.get("domain", "prod")
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
        "domain": domain,
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
