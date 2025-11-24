import threading
import time
from typing import Callable

from ..redis_client import get_redis
from ..config import get_domain


def start_heartbeat(worker_id: str, get_active_jobs: Callable[[], list], interval: float = 2.0) -> threading.Thread:
    r = get_redis()
    domain = get_domain()

    def _beat():
        while True:
            now = time.time()
            r.zadd(f"worker_heartbeats:{domain}", {worker_id: now})
            # Keep current_running in sync with active job count for UI accuracy
            active_jobs = get_active_jobs()
            r.hset(f"workers:{domain}:{worker_id}", mapping={"current_running": len(active_jobs)})
            # Update heartbeat for running jobs
            for job_id in active_jobs:
                r.hset(f"job_running:{domain}:{job_id}", mapping={"worker_id": worker_id, "heartbeat": now})
            time.sleep(interval)

    t = threading.Thread(target=_beat, daemon=True)
    t.start()
    return t
