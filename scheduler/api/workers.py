from fastapi import APIRouter, Request, HTTPException
from typing import List

from ..redis_client import get_redis
from ..models.worker_info import WorkerInfo

router = APIRouter()


@router.get("/workers/", response_model=List[WorkerInfo])
def list_workers(request: Request):
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    workers = []
    domains = [domain] if not is_admin else [key.split(":")[1] for key in r.scan_iter("workers:*") if key.count(":") >= 2]
    domains = list(set(domains))
    if not domains:
        domains = [domain]
    for dom in domains:
        for key in r.scan_iter(f"workers:{dom}:*"):
            parts = key.split(":")
            wid = parts[2] if len(parts) > 2 else parts[-1]
            data = r.hgetall(key)
            hb = r.zscore(f"worker_heartbeats:{dom}", wid)
            running_jobs = list(r.smembers(f"worker_running_set:{dom}:{wid}") or [])
            workers.append(
                WorkerInfo(
                    worker_id=wid,
                    domain=dom,
                    os=data.get("os", ""),
                    tags=(data.get("tags", "") or "").split(",") if data.get("tags") else [],
                    allowed_users=(data.get("allowed_users", "") or "").split(",") if data.get("allowed_users") else [],
                max_concurrency=int(data.get("max_concurrency", 1)),
                    current_running=int(data.get("current_running", 0)),
                    last_heartbeat=hb,
                    status=data.get("status", "online"),
                    state=data.get("state", "online"),
                    cpu_count=int(data.get("cpu_count", 0)) or None,
                    python_version=data.get("python_version"),
                    cwd=data.get("cwd"),
                    hostname=data.get("hostname"),
                    ip=data.get("ip"),
                    subnet=data.get("subnet"),
                    deployment_type=data.get("deployment_type"),
                    run_user=data.get("run_user"),
                    running_jobs=running_jobs,
                )
            )
    return workers


@router.post("/workers/{worker_id}/state")
def set_worker_state(worker_id: str, state: str, request: Request):
    """
    Set worker state to online|draining|disabled.
    Draining/disabled will prevent new dispatches; running jobs continue.
    """
    state = state.lower()
    if state not in {"online", "draining", "disabled"}:
        return {"ok": False, "error": "invalid state"}
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    key = f"workers:{domain}:{worker_id}"
    if not r.exists(key):
        if not is_admin:
            return {"ok": False, "error": "worker not found"}
        # allow admin to target any domain via query param ?domain=
        alt_domain = request.query_params.get("domain")
        if alt_domain and r.exists(f"workers:{alt_domain}:{worker_id}"):
            domain = alt_domain
            key = f"workers:{domain}:{worker_id}"
        else:
            return {"ok": False, "error": "worker not found"}
    r.hset(key, mapping={"state": state})
    return {"ok": True, "state": state}
