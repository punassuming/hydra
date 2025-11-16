import os
import threading
import time
from typing import Dict, List

from .redis_client import get_redis
from .mongo_client import get_db
from .utils.affinity import passes_affinity
from .utils.selectors import select_best_worker
from .utils.failover import failover_once
from .utils.logging import setup_logging


log = setup_logging("scheduler")


def list_online_workers(ttl_seconds: int) -> List[Dict]:
    r = get_redis()
    now = time.time()
    workers: List[Dict] = []
    for key in r.scan_iter("workers:*"):
        worker_id = key.split(":", 1)[1]
        data = r.hgetall(key)
        hb = r.zscore("worker_heartbeats", worker_id) or 0
        # Determine online by TTL
        online = (now - hb) <= ttl_seconds
        if not online:
            continue
        worker = {
            "worker_id": worker_id,
            "os": data.get("os", ""),
            "tags": (data.get("tags", "") or "").split(",") if data.get("tags") else [],
            "allowed_users": (data.get("allowed_users", "") or "").split(",") if data.get("allowed_users") else [],
            "max_concurrency": int(data.get("max_concurrency", 1)),
            "current_running": int(data.get("current_running", 0)),
        }
        # Only accept workers with available slots
        if worker["current_running"] < worker["max_concurrency"]:
            workers.append(worker)
    return workers


def scheduling_loop(stop_event: threading.Event):
    r = get_redis()
    db = get_db()
    ttl = int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10"))
    log.info("Scheduling loop started (heartbeat TTL=%ss)", ttl)
    while not stop_event.is_set():
        try:
            item = r.blpop(["job_queue:pending"], timeout=2)
            if not item:
                continue
            _, job_id = item
            job = db.job_definitions.find_one({"_id": job_id})
            if not job:
                log.error("Received job_id %s with no definition; skipping", job_id)
                continue
            candidates = [w for w in list_online_workers(ttl) if passes_affinity(job, w)]
            worker = select_best_worker(candidates)
            if not worker:
                # No worker matches; requeue and backoff
                log.warning("No eligible worker for job %s; requeuing", job_id)
                r.rpush("job_queue:pending", job_id)
                time.sleep(1)
                continue
            wid = worker["worker_id"]
            r.rpush(f"job_queue:{wid}", job_id)
            # Mark a pending run exists (worker updates on start)
            db.job_runs.insert_one({
                "job_id": job_id,
                "user": job.get("user", ""),
                "worker_id": wid,
                "start_ts": None,
                "end_ts": None,
                "status": "pending",
                "returncode": None,
                "stdout": "",
                "stderr": "",
            })
            log.info("Dispatched job %s to worker %s", job_id, wid)
        except Exception as e:
            log.exception("Error in scheduling loop: %s", e)
            time.sleep(1)


def failover_loop(stop_event: threading.Event):
    ttl = int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10"))
    log.info("Failover loop started (TTL=%ss)", ttl)
    while not stop_event.is_set():
        try:
            failover_once(ttl)
        except Exception as e:
            log.exception("Error in failover loop: %s", e)
        time.sleep(2)
