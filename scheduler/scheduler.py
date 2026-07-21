import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List

from pymongo import ReturnDocument

from .event_bus import event_bus
from .models.job_definition import ScheduleConfig
from .mongo_client import get_db
from .redis_client import get_redis
from .utils.affinity import normalize_affinity, passes_affinity
from .utils.auth import get_domain_token_hash
from .utils.encryption import decrypt_payload
from .utils.failover import failover_once
from .utils.logging import setup_logging
from .utils.schedule import advance_schedule
from .utils.selectors import select_best_worker
from .utils.worker_ops import append_worker_op

log = setup_logging("scheduler")

# SQLAlchemy URL scheme mapping used when building a connection URI from credential fields.
_SQL_DIALECT_MAP = {
    "postgres": "postgresql",
    "mysql": "mysql+pymysql",
    "mssql": "mssql+pyodbc",
    "oracle": "oracle+cx_oracle",
    "mongodb": "mongodb",
}


def _json_ready(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value


def _resolve_credential_refs(job: dict, db) -> dict:
    """If the job's executor or source uses credential_ref, resolve it.

    For SQL executors: resolves credential_ref to connection_uri.
    For HTTP executors: resolves credential_ref to Authorization header.
    For git sources: resolves credential_ref to a token injected into the source.

    This injects decrypted credentials into the job dict so the worker
    (which is Redis-only and has no access to MongoDB) can connect.
    The original job document in Mongo is never mutated.
    Credentials are domain-scoped: only credentials belonging to the
    same domain as the job are resolved.
    """
    job_domain = job.get("domain", "prod")

    # Resolve SQL executor credential_ref
    executor = job.get("executor") or {}
    if executor.get("type") == "sql":
        credential_ref = (executor.get("credential_ref") or "").strip()
        if credential_ref and not (executor.get("connection_uri") or "").strip():
            cred_doc = db.credentials.find_one({"name": credential_ref, "domain": job_domain})
            if not cred_doc:
                log.warning("credential_ref '%s' not found for job %s in domain %s", credential_ref, job.get("_id"), job_domain)
            else:
                try:
                    decrypted = decrypt_payload(cred_doc["encrypted_payload"])
                    # Build connection_uri from decrypted payload
                    resolved_uri = decrypted.get("connection_uri") or ""
                    if not resolved_uri and decrypted.get("host"):
                        dialect = executor.get("dialect", "postgres")
                        user = decrypted.get("username", "")
                        password = decrypted.get("password", "")
                        host = decrypted.get("host", "localhost")
                        port = decrypted.get("port", "")
                        database = decrypted.get("database") or executor.get("database", "")
                        auth = f"{user}:{password}@" if user else ""
                        port_part = f":{port}" if port else ""
                        db_part = f"/{database}" if database else ""
                        dialect_map = {
                            "postgres": "postgresql",
                            "mysql": "mysql+pymysql",
                            "mssql": "mssql+pyodbc",
                            "oracle": "oracle+cx_oracle",
                            "mongodb": "mongodb",
                        }
                        scheme = dialect_map.get(dialect, dialect)
                        resolved_uri = f"{scheme}://{auth}{host}{port_part}{db_part}"
                    if resolved_uri:
                        job = {**job, "executor": {**executor, "connection_uri": resolved_uri}}
                except Exception:
                    log.exception("Failed to decrypt credential '%s' for job %s", credential_ref, job.get("_id"))

    # Resolve HTTP executor credential_ref → inject Authorization header
    if executor.get("type") == "http":
        credential_ref = (executor.get("credential_ref") or "").strip()
        if credential_ref:
            cred_doc = db.credentials.find_one({"name": credential_ref, "domain": job_domain})
            if not cred_doc:
                log.warning(
                    "credential_ref '%s' not found for http job %s in domain %s", credential_ref, job.get("_id"), job_domain
                )
            else:
                try:
                    decrypted = decrypt_payload(cred_doc["encrypted_payload"])
                    # Support token (Bearer), api_key (X-API-Key), or username:password (Basic)
                    headers = dict(executor.get("headers") or {})
                    if decrypted.get("token"):
                        headers["Authorization"] = f"Bearer {decrypted['token']}"
                    elif decrypted.get("api_key"):
                        headers["X-API-Key"] = decrypted["api_key"]
                    elif decrypted.get("username") and decrypted.get("password"):
                        import base64
                        creds = base64.b64encode(f"{decrypted['username']}:{decrypted['password']}".encode()).decode()
                        headers["Authorization"] = f"Basic {creds}"
                    job = {**job, "executor": {**executor, "headers": headers}}
                except Exception:
                    log.exception("Failed to decrypt credential '%s' for http job %s", credential_ref, job.get("_id"))

    # Resolve source credential_ref (git PAT)
    source = job.get("source") or {}
    src_credential_ref = (source.get("credential_ref") or "").strip()
    if src_credential_ref and not source.get("token"):
        cred_doc = db.credentials.find_one({"name": src_credential_ref, "domain": job_domain})
        if not cred_doc:
            log.warning(
                "source credential_ref '%s' not found for job %s in domain %s", src_credential_ref, job.get("_id"), job_domain
            )
        else:
            try:
                decrypted = decrypt_payload(cred_doc["encrypted_payload"])
                token = decrypted.get("token") or decrypted.get("password") or ""
                if token:
                    job = {**job, "source": {**source, "token": token}}
            except Exception:
                log.exception("Failed to decrypt source credential '%s' for job %s", src_credential_ref, job.get("_id"))

    # Resolve sensor executor credential_ref
    # Sensor jobs are dispatched to workers like any other job; credentials
    # must be resolved here before the job envelope is pushed to Redis.
    if executor.get("type") == "sensor":
        credential_ref = (executor.get("credential_ref") or "").strip()
        if credential_ref:
            sensor_type = executor.get("sensor_type", "http")
            cred_doc = db.credentials.find_one({"name": credential_ref, "domain": job_domain})
            if not cred_doc:
                log.warning(
                    "sensor credential_ref '%s' not found for job %s in domain %s", credential_ref, job.get("_id"), job_domain
                )
            else:
                try:
                    decrypted = decrypt_payload(cred_doc["encrypted_payload"])
                    if sensor_type == "sql":
                        connection_uri = decrypted.get("connection_uri") or ""
                        if not connection_uri and decrypted.get("host"):
                            dialect = executor.get("dialect", "postgres")
                            user = decrypted.get("username", "")
                            password = decrypted.get("password", "")
                            host = decrypted.get("host", "localhost")
                            port = decrypted.get("port", "")
                            database = decrypted.get("database", "")
                            auth = f"{user}:{password}@" if user else ""
                            port_part = f":{port}" if port else ""
                            db_part = f"/{database}" if database else ""
                            scheme = _SQL_DIALECT_MAP.get(dialect, dialect)
                            connection_uri = f"{scheme}://{auth}{host}{port_part}{db_part}"
                        if connection_uri:
                            job = {**job, "executor": {**executor, "connection_uri": connection_uri}}
                    else:
                        headers = dict(executor.get("headers") or {})
                        if decrypted.get("token"):
                            headers["Authorization"] = f"Bearer {decrypted['token']}"
                        elif decrypted.get("api_key"):
                            headers["X-API-Key"] = decrypted["api_key"]
                        elif decrypted.get("username") and decrypted.get("password"):
                            import base64
                            creds = base64.b64encode(
                                f"{decrypted['username']}:{decrypted['password']}".encode()
                            ).decode()
                            headers["Authorization"] = f"Basic {creds}"
                        job = {**job, "executor": {**executor, "headers": headers}}
                except Exception:
                    log.exception("Failed to decrypt sensor credential '%s' for job %s", credential_ref, job.get("_id"))

    return job


def list_online_workers(ttl_seconds: int, domain: str, respect_capacity: bool = True) -> List[Dict]:
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
        expected_hash = get_domain_token_hash(domain)
        worker_hash = data.get("domain_token_hash")
        if expected_hash and worker_hash and worker_hash != expected_hash:
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
            "state": data.get("state", "online"),
            "capabilities": (data.get("capabilities", "") or "").split(",") if data.get("capabilities") else [],
        }
        # Only accept workers with available slots
        if worker["state"] != "online":
            continue
        if (not respect_capacity) or (worker["current_running"] < worker["max_concurrency"]):
            workers.append(worker)
    return workers


def scheduling_loop(stop_event: threading.Event):
    r = get_redis()
    db = get_db()
    ttl = int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10"))
    # After this many consecutive no-worker cycles for a single job, log a
    # starvation warning so operators know the job is blocked.
    starvation_warn_threshold = int(os.getenv("SCHEDULER_STARVATION_WARN_THRESHOLD", "5"))
    # Hard cap on how many bypass_concurrency jobs a single worker may carry
    # above its normal max_concurrency.  0 means no cap (default: no cap).
    bypass_max_extra = int(os.getenv("SCHEDULER_BYPASS_MAX_EXTRA", "0"))
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
            bypass_concurrency = bool(job.get("bypass_concurrency", False))
            meta_key = f"job_enqueue_meta:{domain}:{job_id}"
            meta = r.hgetall(meta_key) or {}
            enqueued_ts = float(meta.get("enqueued_ts", time.time()))
            enqueue_reason = meta.get("reason")
            retry_attempt = int(meta.get("retry_attempt", 0))
            no_worker_count = int(meta.get("no_worker_count", 0))
            params_raw = meta.get("params")
            r.delete(meta_key)

            # Sensor jobs are dispatched through the normal worker path.
            # Workers execute the sensor polling loop directly, keeping the
            # scheduler free from external workload polling.
            job = normalize_affinity(job)
            candidates = [
                w
                for w in list_online_workers(ttl, domain, respect_capacity=not bypass_concurrency)
                if passes_affinity(job, w)
            ]

            # bypass_concurrency guardrail: if a per-worker extra-bypass cap is
            # configured, exclude workers that already have too many bypass jobs
            # running above their normal capacity limit.
            if bypass_concurrency and bypass_max_extra > 0:
                filtered = []
                for w in candidates:
                    extra = max(0, int(w.get("current_running", 0)) - int(w.get("max_concurrency", 1)))
                    if extra < bypass_max_extra:
                        filtered.append(w)
                    else:
                        log.warning(
                            "Worker %s has %d bypass job(s) running (cap=%d); skipping for bypass job %s",
                            w["worker_id"], extra, bypass_max_extra, job_id,
                        )
                candidates = filtered

            worker = select_best_worker(candidates)
            if not worker:
                # No worker matches; requeue and backoff.
                no_worker_count += 1
                if no_worker_count == starvation_warn_threshold:
                    log.warning(
                        "Job %s has been waiting for an eligible worker %d time(s) "
                        "(starvation risk; bypass_concurrency=%s)",
                        job_id, no_worker_count, bypass_concurrency,
                    )
                elif no_worker_count > starvation_warn_threshold and no_worker_count % starvation_warn_threshold == 0:
                    log.warning(
                        "Job %s still waiting for eligible worker after %d attempt(s)",
                        job_id, no_worker_count,
                    )
                else:
                    log.warning("No eligible worker for job %s; requeuing (no_worker_count=%d)", job_id, no_worker_count)
                r.zadd(f"job_queue:{domain}:pending", {job_id: float(job.get("priority", 5))})
                new_meta: dict = {
                    "enqueued_ts": enqueued_ts,
                    "reason": enqueue_reason or "no_worker",
                    "no_worker_count": no_worker_count,
                }
                if params_raw:
                    new_meta["params"] = params_raw
                r.hset(meta_key, mapping=new_meta)
                r.expire(meta_key, 24 * 3600)
                event_bus.publish(
                    "job_pending",
                    {"job_id": job_id, "reason": "no_worker", "domain": domain, "no_worker_count": no_worker_count},
                )
                time.sleep(1)
                continue
            wid = worker["worker_id"]
            dispatched_job = _resolve_credential_refs(job, db)
            try:
                params = json.loads(params_raw) if params_raw else {}
            except (json.JSONDecodeError, TypeError):
                log.warning("Invalid params JSON for job %s; using empty params", job_id)
                params = {}

            # Warn when dispatching a bypass_concurrency job to a worker that is
            # already at or above its normal concurrency limit.
            if bypass_concurrency:
                current = int(worker.get("current_running", 0))
                cap = int(worker.get("max_concurrency", 1))
                if current >= cap:
                    log.warning(
                        "Dispatching bypass_concurrency job %s to worker %s which is already at capacity "
                        "(%d/%d); this may overload the worker",
                        job_id, wid, current, cap,
                    )

            envelope = {
                "job_id": job_id,
                "domain": domain,
                "job": _json_ready(dispatched_job),
                "enqueued_ts": enqueued_ts,
                "dispatch_ts": time.time(),
                "enqueue_reason": enqueue_reason,
                "retry_attempt": retry_attempt,
                "params": params,
            }
            r.rpush(f"job_queue:{domain}:{wid}", json.dumps(envelope))
            append_worker_op(
                domain=domain,
                worker_id=wid,
                op_type="dispatch",
                message=f"Job {job_id} dispatched",
                details={
                    "job_id": job_id,
                    "bypass_concurrency": bypass_concurrency,
                    "enqueue_reason": enqueue_reason,
                    "no_worker_count": no_worker_count,
                },
            )
            # Mark a pending run exists (worker updates on start)
            event_bus.publish(
                "job_dispatched",
                {
                    "job_id": job_id,
                    "worker_id": wid,
                    "domain": domain,
                    "bypass_concurrency": bypass_concurrency,
                },
            )
            log.info("Dispatched job %s to worker %s (bypass_concurrency=%s)", job_id, wid, bypass_concurrency)
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
            now = datetime.now(timezone.utc)
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


def sla_monitoring_loop(stop_event: threading.Event):
    from .run_events import _fire_email_alert_async, _fire_webhooks_async
    db = get_db()
    log.info("SLA monitoring loop started")
    while not stop_event.is_set():
        try:
            now = datetime.now(timezone.utc)
            cursor = db.job_runs.find(
                {"status": "running", "sla_miss_alerted": {"$ne": True}},
                {"_id": 1, "job_id": 1, "domain": 1, "start_ts": 1},
            )
            for run_doc in cursor:
                run_id = run_doc.get("_id")
                job_id = run_doc.get("job_id")
                domain = run_doc.get("domain", "prod")
                start_ts = run_doc.get("start_ts")
                if not start_ts or not job_id:
                    continue
                if not isinstance(start_ts, datetime):
                    try:
                        start_ts = datetime.fromisoformat(str(start_ts))
                    except Exception:
                        continue
                elapsed = (now - start_ts).total_seconds()
                job_doc = db.job_definitions.find_one(
                    {"_id": job_id},
                    {
                        "sla_max_duration_seconds": 1,
                        "on_failure_webhooks": 1,
                        "on_failure_email_to": 1,
                        "on_failure_email_credential_ref": 1,
                    },
                )
                if not job_doc:
                    continue
                sla_seconds = job_doc.get("sla_max_duration_seconds")
                try:
                    sla_seconds = int(sla_seconds) if sla_seconds is not None else 0
                except (TypeError, ValueError):
                    continue
                if sla_seconds <= 0:
                    continue
                if elapsed > sla_seconds:
                    result = db.job_runs.update_one(
                        {"_id": run_id, "sla_miss_alerted": {"$ne": True}},
                        {"$set": {"sla_miss_alerted": True}},
                    )
                    if result.modified_count == 0:
                        continue
                    log.warning(
                        "SLA missed for job %s run %s (%.1fs > %ss); firing alerts",
                        job_id, run_id, elapsed, sla_seconds,
                    )
                    alert_message = (
                        f"SLA Warning: Job exceeded expected duration of {sla_seconds} seconds "
                        f"(running for {elapsed:.1f}s)"
                    )
                    webhooks = job_doc.get("on_failure_webhooks") or []
                    _fire_webhooks_async(webhooks, job_id, run_id, alert_message)
                    email_to = job_doc.get("on_failure_email_to") or []
                    email_cred_ref = str(job_doc.get("on_failure_email_credential_ref") or "").strip()
                    _fire_email_alert_async(db, domain, email_cred_ref, email_to, job_id, run_id, alert_message)
        except Exception as exc:
            log.exception("Error in SLA monitoring loop: %s", exc)
        time.sleep(30)


def timeout_enforcement_loop(stop_event: threading.Event):
    r = get_redis()
    db = get_db()
    log.info("Timeout enforcement loop started")
    while not stop_event.is_set():
        try:
            now = time.time()
            domains = list(r.smembers("hydra:domains") or []) or ["prod"]
            for domain in domains:
                for key in r.scan_iter(f"job_running:{domain}:*"):
                    data = r.hgetall(key) or {}
                    job_id = key.split(":")[-1]
                    run_id = data.get("run_id")
                    if not run_id:
                        continue
                    started_ts = float(data.get("heartbeat", now))
                    elapsed = now - started_ts
                    job_doc = db.job_definitions.find_one({"_id": job_id}, {"timeout": 1})
                    if not job_doc:
                        continue
                    job_timeout = int(job_doc.get("timeout", 0))
                    if job_timeout > 0 and elapsed > job_timeout:
                        log.warning(
                            "Timeout exceeded for job %s run %s (%.1fs > %ss); sending kill signal",
                            job_id, run_id, elapsed, job_timeout,
                        )
                        r.publish(f"job_kill:{domain}", run_id)
        except Exception as exc:
            log.exception("Error in timeout enforcement loop: %s", exc)
        time.sleep(5)


def backfill_dispatch_loop(stop_event: threading.Event):
    """Process backfill queue items and dispatch them to available workers.

    Each item in ``backfill_queue:{domain}`` (a Redis list) is a JSON object
    with ``job_id``, ``execution_date``, ``priority``, and ``domain``.  For
    each item, the loop selects an available worker using the same affinity and
    capacity rules as the main scheduling loop, then pushes a job envelope to
    the worker's queue with ``HYDRA_EXECUTION_DATE`` and ``HYDRA_IS_BACKFILL``
    injected as runtime parameters (env vars).
    """
    r = get_redis()
    db = get_db()
    ttl = int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10"))
    log.info("Backfill dispatch loop started (heartbeat TTL=%ss)", ttl)
    while not stop_event.is_set():
        try:
            domains = list(r.smembers("hydra:domains") or []) or ["prod"]
            backfill_keys = [f"backfill_queue:{d}" for d in domains]
            popped = r.blpop(backfill_keys, timeout=2)
            if not popped:
                continue
            _key, raw = popped
            try:
                item = json.loads(raw)
            except Exception:
                log.warning("Invalid backfill queue item (not JSON): %s", raw)
                continue

            job_id = item.get("job_id", "")
            execution_date = item.get("execution_date", "")
            domain = item.get("domain", "prod")

            if not job_id or not execution_date:
                log.warning("Backfill item missing job_id or execution_date; skipping")
                continue

            job = db.job_definitions.find_one({"_id": job_id})
            if not job:
                log.error("Backfill: job_id %s not found; skipping date %s", job_id, execution_date)
                continue

            domain = job.get("domain", domain)
            bypass_concurrency = bool(job.get("bypass_concurrency", False))

            job = normalize_affinity(job)
            candidates = [
                w
                for w in list_online_workers(ttl, domain, respect_capacity=not bypass_concurrency)
                if passes_affinity(job, w)
            ]
            worker = select_best_worker(candidates)
            if not worker:
                # No worker available; put the item back at the front of the queue and back off.
                log.warning(
                    "Backfill: no eligible worker for job %s date %s; requeuing",
                    job_id, execution_date,
                )
                r.lpush(f"backfill_queue:{domain}", raw)
                time.sleep(2)
                continue

            wid = worker["worker_id"]
            dispatched_job = _resolve_credential_refs(job, db)
            enqueued_ts = time.time()
            envelope = {
                "job_id": job_id,
                "domain": domain,
                "job": _json_ready(dispatched_job),
                "enqueued_ts": enqueued_ts,
                "dispatch_ts": time.time(),
                "enqueue_reason": "backfill",
                "retry_attempt": 0,
                "params": {
                    "HYDRA_EXECUTION_DATE": execution_date,
                    "HYDRA_IS_BACKFILL": "true",
                },
            }
            r.rpush(f"job_queue:{domain}:{wid}", json.dumps(envelope))
            append_worker_op(
                domain=domain,
                worker_id=wid,
                op_type="dispatch",
                message=f"Backfill job {job_id} dispatched (date={execution_date})",
                details={
                    "job_id": job_id,
                    "execution_date": execution_date,
                    "enqueue_reason": "backfill",
                    "bypass_concurrency": bypass_concurrency,
                },
            )
            event_bus.publish(
                "job_dispatched",
                {
                    "job_id": job_id,
                    "worker_id": wid,
                    "domain": domain,
                    "bypass_concurrency": bypass_concurrency,
                    "execution_date": execution_date,
                    "enqueue_reason": "backfill",
                },
            )
            log.info(
                "Dispatched backfill job %s (date=%s) to worker %s",
                job_id, execution_date, wid,
            )
        except Exception as e:
            log.exception("Error in backfill dispatch loop: %s", e)
            time.sleep(1)
