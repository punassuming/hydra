import threading
import time
from typing import Callable

from ..redis_client import get_redis


def start_heartbeat(worker_id: str, get_active_jobs: Callable[[], list], interval: float = 2.0) -> threading.Thread:
    r = get_redis()

    def _beat():
        while True:
            now = time.time()
            r.zadd("worker_heartbeats", {worker_id: now})
            # Update heartbeat for running jobs
            for job_id in get_active_jobs():
                r.hset(f"job_running:{job_id}", mapping={"worker_id": worker_id, "heartbeat": now})
            time.sleep(interval)

    t = threading.Thread(target=_beat, daemon=True)
    t.start()
    return t

