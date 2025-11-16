import time
from typing import List

from ..redis_client import get_redis
from ..mongo_client import get_db
from .logging import setup_logging


log = setup_logging("scheduler.failover")


def find_offline_workers(ttl_seconds: int) -> List[str]:
    r = get_redis()
    now = time.time()
    offline = []
    # Get all workers with heartbeat older than TTL
    heartbeats = r.zrange("worker_heartbeats", 0, -1, withscores=True)
    for worker_id, ts in heartbeats:
        if now - ts > ttl_seconds:
            offline.append(worker_id)
    return offline


def requeue_jobs_for_worker(worker_id: str):
    r = get_redis()
    db = get_db()
    set_key = f"worker_running_set:{worker_id}"
    job_ids = r.smembers(set_key) or []
    if job_ids:
        log.warning("Requeuing %d job(s) from offline worker %s", len(job_ids), worker_id)
    for job_id in job_ids:
        # Clean running markers and requeue
        r.delete(f"job_running:{job_id}")
        r.rpush("job_queue:pending", job_id)
        r.srem(set_key, job_id)
        # Optionally update last run doc to pending again (leave as is; worker will update when rerun)
    # Reset current_running counter to 0
    r.hset(f"workers:{worker_id}", mapping={"current_running": 0, "status": "offline"})


def failover_once(ttl_seconds: int):
    offline_workers = find_offline_workers(ttl_seconds)
    for wid in offline_workers:
        requeue_jobs_for_worker(wid)

