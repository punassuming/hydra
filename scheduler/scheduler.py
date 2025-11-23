import os
import threading
import time
from datetime import datetime
from typing import Dict, List

from pymongo import ReturnDocument

from .redis_client import get_redis
from .mongo_client import get_db
from .utils.affinity import passes_affinity
from .utils.selectors import select_best_worker
from .utils.failover import failover_once
from .utils.logging import setup_logging
from .event_bus import event_bus
from .models.job_definition import ScheduleConfig
from .utils.schedule import advance_schedule


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
            "hostname": data.get("hostname", ""),
            "ip": data.get("ip", ""),
            "subnet": data.get("subnet", ""),
            "deployment_type": data.get("deployment_type", ""),
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
                event_bus.publish("job_pending", {"job_id": job_id, "reason": "no_worker"})
                time.sleep(1)
                continue
            wid = worker["worker_id"]
            r.rpush(f"job_queue:{wid}", job_id)
            # Mark a pending run exists (worker updates on start)
            event_bus.publish("job_dispatched", {"job_id": job_id, "worker_id": wid})
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


def schedule_trigger_loop(stop_event: threading.Event):
    r = get_redis()
    db = get_db()
    log.info("Schedule trigger loop started")
    while not stop_event.is_set():
        try:
            now = datetime.utcnow()
            due_jobs = db.job_definitions.find(
                {
                    "schedule.mode": {"$in": ["cron", "interval"]},
                    "schedule.enabled": True,
                    "schedule.next_run_at": {"$ne": None, "$lte": now},
                }
            ).limit(100)
            for job in due_jobs:
                schedule_doc = job.get("schedule") or {}
                next_run_at = schedule_doc.get("next_run_at")
                if not next_run_at:
                    continue
                schedule = ScheduleConfig.model_validate(schedule_doc)
                advanced = advance_schedule(schedule)
                updated = db.job_definitions.find_one_and_update(
                    {
                        "_id": job["_id"],
                        "schedule.next_run_at": next_run_at,
                    },
                    {"$set": {"schedule": advanced.model_dump(by_alias=True)}},
                    return_document=ReturnDocument.AFTER,
                )
                if not updated:
                    continue
                r.rpush("job_queue:pending", job["_id"])
                event_bus.publish(
                    "job_scheduled",
                    {
                        "job_id": job["_id"],
                        "mode": schedule.mode,
                        "next_run_at": advanced.next_run_at.isoformat() if advanced.next_run_at else None,
                    },
                )
        except Exception as exc:
            log.exception("Error in schedule trigger loop: %s", exc)
            time.sleep(1)
        time.sleep(1)
