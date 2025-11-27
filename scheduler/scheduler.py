import os
import threading
import time
import hashlib
from datetime import datetime
from typing import Dict, List

from pymongo import ReturnDocument

from .redis_client import get_redis
from .mongo_client import get_db
from .utils.affinity import passes_affinity
from .utils.selectors import select_best_worker
from .utils.failover import failover_once
from .utils.logging import setup_logging
from .utils.auth import _hash_token
from .event_bus import event_bus
from .models.job_definition import ScheduleConfig
from .utils.schedule import advance_schedule


log = setup_logging("scheduler")


def list_online_workers(ttl_seconds: int, domain: str) -> List[Dict]:
    r = get_redis()
    now = time.time()
    workers: List[Dict] = []
    for key in r.scan_iter(f"workers:{domain}:*"):
        parts = key.split(":")
        worker_id = parts[2] if len(parts) > 2 else parts[-1]
        data = r.hgetall(key)
        hb = r.zscore(f"worker_heartbeats:{domain}", worker_id) or 0
        # Determine online by TTL
        online = (now - hb) <= ttl_seconds
        if not online:
            continue
        expected_hash = r.get(f"token_hash:{domain}")
        worker_hash = data.get("domain_token_hash")
        if expected_hash and worker_hash and worker_hash != expected_hash:
            continue
        worker = {
            "worker_id": worker_id,
            "os": data.get("os", ""),
            "tags": (data.get("tags", "") or "").split(",") if data.get("tags") else [],
            "allowed_users": (data.get("allowed_users", "") or "").split(",") if data.get("allowed_users") else [],
            "queues": (data.get("queues", "") or "").split(",") if data.get("queues") else ["default"],
            "max_concurrency": int(data.get("max_concurrency", 1)),
            "current_running": int(data.get("current_running", 0)),
            "hostname": data.get("hostname", ""),
            "ip": data.get("ip", ""),
            "subnet": data.get("subnet", ""),
            "deployment_type": data.get("deployment_type", ""),
            "state": data.get("state", "online"),
        }
        # Only accept workers with available slots
        if worker["state"] != "online":
            continue
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
            domains = list(r.smembers("hydra:domains") or []) or ["prod"]
            pending_keys = [f"job_queue:{d}:pending" for d in domains]
            popped = r.bzpopmax(pending_keys, timeout=2)
            if not popped:
                continue
            key, job_id, _score = popped
            domain = key.split(":")[1] if ":" in key else "prod"
            job = db.job_definitions.find_one({"_id": job_id})
            if not job:
                log.error("Received job_id %s with no definition; skipping", job_id)
                continue
            domain = job.get("domain", domain)
            candidates = [
                w
                for w in list_online_workers(ttl, domain)
                if passes_affinity(job, w)
            ]
            worker = select_best_worker(candidates)
            if not worker:
                # No worker matches; requeue and backoff
                log.warning("No eligible worker for job %s; requeuing", job_id)
                r.zadd(f"job_queue:{domain}:pending", {job_id: float(job.get("priority", 5))})
                event_bus.publish("job_pending", {"job_id": job_id, "reason": "no_worker", "domain": domain})
                time.sleep(1)
                continue
            wid = worker["worker_id"]
            r.rpush(f"job_queue:{domain}:{wid}", job_id)
            # Mark a pending run exists (worker updates on start)
            event_bus.publish("job_dispatched", {"job_id": job_id, "worker_id": wid, "domain": domain})
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
            domains = list(r.smembers("hydra:domains") or []) or ["prod"]
            for domain in domains:
                due_jobs = db.job_definitions.find(
                    {
                        "domain": domain,
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
                    priority = int(job.get("priority", 5))
                    r.zadd(f"job_queue:{domain}:pending", {job["_id"]: priority})
                    event_bus.publish(
                        "job_scheduled",
                        {
                            "job_id": job["_id"],
                            "mode": schedule.mode,
                            "next_run_at": advanced.next_run_at.isoformat() if advanced.next_run_at else None,
                            "domain": domain,
                        },
                    )
        except Exception as exc:
            log.exception("Error in schedule trigger loop: %s", exc)
            time.sleep(1)
        time.sleep(1)
