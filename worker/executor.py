from datetime import datetime
from typing import Tuple

from bson import ObjectId

from .mongo_client import get_db
from .utils.os_exec import run_command


def execute_job(job: dict) -> Tuple[int, str, str]:
    shell = job.get("shell", "bash")
    command = job.get("command", "")
    timeout = job.get("timeout", 0) or None
    return run_command(command, shell=shell, timeout=timeout)


def record_run_start(job_id: str, user: str, worker_id: str) -> str:
    db = get_db()
    run_doc = {
        "job_id": job_id,
        "user": user,
        "worker_id": worker_id,
        "start_ts": datetime.utcnow(),
        "end_ts": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    res = db.job_runs.insert_one(run_doc)
    return str(res.inserted_id)


def record_run_end(run_id: str, returncode: int, stdout: str, stderr: str):
    db = get_db()
    status = "success" if returncode == 0 else "failed"
    db.job_runs.update_one(
        {"_id": ObjectId(run_id)},
        {
            "$set": {
                "end_ts": datetime.utcnow(),
                "status": status,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        },
    )
