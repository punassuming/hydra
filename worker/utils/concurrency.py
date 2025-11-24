from ..redis_client import get_redis
from ..config import get_domain


def incr_running(worker_id: str, delta: int) -> int:
    r = get_redis()
    key = f"workers:{get_domain()}:{worker_id}"
    return r.hincrby(key, "current_running", delta)


def add_active_job(worker_id: str, job_id: str):
    r = get_redis()
    r.sadd(f"worker_running_set:{get_domain()}:{worker_id}", job_id)


def remove_active_job(worker_id: str, job_id: str):
    r = get_redis()
    r.srem(f"worker_running_set:{get_domain()}:{worker_id}", job_id)
