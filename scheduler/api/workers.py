from fastapi import APIRouter
from typing import List

from ..redis_client import get_redis
from ..models.worker_info import WorkerInfo

router = APIRouter()


@router.get("/workers/", response_model=List[WorkerInfo])
def list_workers():
    r = get_redis()
    workers = []
    for key in r.scan_iter("workers:*"):
        wid = key.split(":", 1)[1]
        data = r.hgetall(key)
        hb = r.zscore("worker_heartbeats", wid)
        workers.append(
            WorkerInfo(
                worker_id=wid,
                os=data.get("os", ""),
                tags=(data.get("tags", "") or "").split(",") if data.get("tags") else [],
                allowed_users=(data.get("allowed_users", "") or "").split(",") if data.get("allowed_users") else [],
                max_concurrency=int(data.get("max_concurrency", 1)),
                current_running=int(data.get("current_running", 0)),
                last_heartbeat=hb,
                status=data.get("status", "online"),
                cpu_count=int(data.get("cpu_count", 0)) or None,
                python_version=data.get("python_version"),
                cwd=data.get("cwd"),
            )
        )
    return workers
