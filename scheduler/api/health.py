from fastapi import APIRouter, Request
from ..redis_client import get_redis

router = APIRouter()


@router.get("/health")
def health(request: Request):
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    # Return lightweight health stats
    workers_count = len(list(r.scan_iter(f"workers:{domain}:*")))
    pending = r.zcard(f"job_queue:{domain}:pending")
    return {"status": "ok", "workers": workers_count, "pending_jobs": pending}
