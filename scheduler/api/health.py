from fastapi import APIRouter
from ..redis_client import get_redis

router = APIRouter()


@router.get("/health")
def health():
    r = get_redis()
    # Return lightweight health stats
    workers_count = len(r.keys("workers:*"))
    pending = r.llen("job_queue:pending")
    return {"status": "ok", "workers": workers_count, "pending_jobs": pending}

