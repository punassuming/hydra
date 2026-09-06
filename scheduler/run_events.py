import json
import smtplib
import threading
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict

from pymongo.errors import DuplicateKeyError

from .models.job_run import TERMINAL_STATES
from .mongo_client import get_db
from .redis_client import get_redis
from .utils.encryption import decrypt_payload
from .utils.logging import setup_logging
from .utils.worker_ops import append_worker_op

log = setup_logging("scheduler.run_events")
# Maximum length of error_message sent in webhook payloads
_WEBHOOK_MAX_ERROR_LEN = 2000


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized)
        except Exception:
            return None
    return None


def _enqueue_job_for_retry(job_id: str, domain: str, priority: int, retry_attempt: int, delay_seconds: int = 0):
    """Re-enqueue a failed job for a scheduler-level retry, with optional delay."""
    def _do():
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        r = get_redis()
        r.zadd(f"job_queue:{domain}:pending", {job_id: float(priority)})
        r.hset(
            f"job_enqueue_meta:{domain}:{job_id}",
            mapping={
                "enqueued_ts": time.time(),
                "reason": f"scheduler_retry_{retry_attempt}",
                "retry_attempt": str(retry_attempt),
            },
        )
        r.expire(f"job_enqueue_meta:{domain}:{job_id}", 24 * 3600)
        log.info("Requeued job %s for retry attempt %s (delay=%ss)", job_id, retry_attempt, delay_seconds)

    t = threading.Thread(target=_do, daemon=True)
    t.start()


def _trigger_dependents(job_id: str, domain: str, db):
    """Enqueue any jobs whose depends_on includes the just-completed job_id."""
    dependents = list(db.job_definitions.find(
        {"domain": domain, "depends_on": job_id, "schedule.enabled": True}
    ))
    if not dependents:
        return
    r = get_redis()
    for dep_job in dependents:
        dep_id = dep_job["_id"]
        priority = int(dep_job.get("priority", 5))
        r.zadd(f"job_queue:{domain}:pending", {dep_id: float(priority)})
        r.hset(
            f"job_enqueue_meta:{domain}:{dep_id}",
            mapping={"enqueued_ts": time.time(), "reason": f"dependency_of_{job_id}"},
        )
        r.expire(f"job_enqueue_meta:{domain}:{dep_id}", 24 * 3600)
        log.info("Triggered dependent job %s because %s succeeded", dep_id, job_id)


def _fire_webhooks(webhooks: list, job_id: str, run_id: str, error_message: str):
    """Fire HTTP POST to each webhook URL with failure details."""
    payload = json.dumps({
        "job_id": job_id,
        "run_id": run_id,
        "error_message": error_message,
    }).encode()
    for url in webhooks:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            log.warning("Webhook POST failed for %s: %s", url, exc)


def _fire_webhooks_async(webhooks: list, job_id: str, run_id: str, error_message: str):
    if not webhooks:
        return
    t = threading.Thread(target=_fire_webhooks, args=(webhooks, job_id, run_id, error_message), daemon=True)
    t.start()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _fire_email_alert(db, domain: str, credential_ref: str, recipients: list[str], job_id: str, run_id: str, error_message: str):
    if not recipients or not credential_ref:
        return

    cred_doc = db.credentials.find_one({"name": credential_ref, "domain": domain})
    if not cred_doc:
        log.warning("Email alert credential '%s' not found in domain '%s'", credential_ref, domain)
        return

    try:
        smtp = decrypt_payload(cred_doc.get("encrypted_payload", ""))
    except Exception as exc:
        log.warning("Failed to decrypt SMTP credential '%s': %s", credential_ref, exc)
        return

    host = str(smtp.get("host") or "").strip()
    username = str(smtp.get("username") or "").strip()
    password = str(smtp.get("password") or "")
    sender = str(smtp.get("from_email") or username or "hydra@localhost").strip()
    use_ssl = _as_bool(smtp.get("use_ssl"), False)
    use_tls = _as_bool(smtp.get("use_tls"), not use_ssl)
    port = int(smtp.get("port") or (465 if use_ssl else 587 if use_tls else 25))
    timeout = int(smtp.get("timeout_seconds") or 10)

    if not host:
        log.warning("SMTP credential '%s' is missing host", credential_ref)
        return

    clean_recipients = [str(r).strip() for r in recipients if str(r).strip()]
    if not clean_recipients:
        return

    msg = EmailMessage()
    msg["Subject"] = f"[Hydra] Job failed: {job_id}"
    msg["From"] = sender
    msg["To"] = ", ".join(clean_recipients)
    msg.set_content(
        "\n".join(
            [
                "Hydra job failure alert",
                f"domain: {domain}",
                f"job_id: {job_id}",
                f"run_id: {run_id}",
                "",
                "error:",
                error_message or "(no error text)",
            ]
        )
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host=host, port=port, timeout=timeout) as client:
                if username:
                    client.login(username, password)
                client.send_message(msg)
        else:
            with smtplib.SMTP(host=host, port=port, timeout=timeout) as client:
                if use_tls:
                    client.starttls()
                if username:
                    client.login(username, password)
                client.send_message(msg)
    except Exception as exc:
        log.warning("Email alert send failed for job %s: %s", job_id, exc)


def _fire_email_alert_async(
    db, domain: str, credential_ref: str, recipients: list[str], job_id: str, run_id: str, error_message: str
):
    if not recipients or not credential_ref:
        return
    t = threading.Thread(
        target=_fire_email_alert,
        args=(db, domain, credential_ref, recipients, job_id, run_id, error_message),
        daemon=True,
    )
    t.start()


def _handle_run_start(payload: Dict[str, Any]):
    db = get_db()
    run_id = str(payload.get("run_id") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    if not run_id or not job_id:
        return

    start_ts = _to_datetime(payload.get("start_ts")) or datetime.now(timezone.utc)
    scheduled_ts = _to_datetime(payload.get("scheduled_ts")) or start_ts
    doc = {
        "_id": run_id,
        "job_id": job_id,
        "user": payload.get("user", ""),
        "domain": payload.get("domain", "prod"),
        "worker_id": payload.get("worker_id"),
        "start_ts": start_ts,
        "scheduled_ts": scheduled_ts,
        "end_ts": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "slot": payload.get("slot"),
        "attempt": payload.get("attempt", 1),
        "retries_remaining": payload.get("retries_remaining"),
        "schedule_tick": payload.get("schedule_tick"),
        "schedule_mode": payload.get("schedule_mode"),
        "executor_type": payload.get("executor_type"),
        "queue_latency_ms": payload.get("queue_latency_ms"),
        "completion_reason": None,
        "bypass_concurrency": bool(payload.get("bypass_concurrency", False)),
    }

    # Idempotent insert: $setOnInsert is a no-op when the document already
    # exists, preventing duplicate run_start events from overwriting fields
    # (including terminal status values written by a preceding run_end).
    result = db.job_runs.update_one(
        {"_id": run_id},
        {"$setOnInsert": doc},
        upsert=True,
    )

    if result.matched_count > 0:
        # Document already existed — this is a duplicate or replayed event.
        existing = db.job_runs.find_one({"_id": run_id}, {"status": 1})
        existing_status = (existing or {}).get("status", "unknown")
        if existing_status in TERMINAL_STATES:
            log.warning(
                "Duplicate run_start for already-terminal run %s (status=%s, job=%s); ignoring",
                run_id, existing_status, job_id,
            )
        else:
            log.warning(
                "Duplicate run_start for run %s (current status=%s, job=%s); ignoring",
                run_id, existing_status, job_id,
            )
        return

    worker_id = payload.get("worker_id")
    domain = payload.get("domain", "prod")
    if worker_id:
        append_worker_op(
            domain=domain,
            worker_id=worker_id,
            op_type="run_start",
            message=f"Started job {job_id}",
            details={
                "run_id": run_id,
                "job_id": job_id,
                "slot": payload.get("slot"),
                "attempt": payload.get("attempt", 1),
            },
            ts=start_ts.timestamp(),
        )


def _handle_run_end(payload: Dict[str, Any]):
    db = get_db()
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        return

    end_ts = _to_datetime(payload.get("end_ts")) or datetime.now(timezone.utc)
    existing = db.job_runs.find_one({"_id": run_id}, {"start_ts": 1, "status": 1})
    start_ts = _to_datetime((existing or {}).get("start_ts")) or _to_datetime(payload.get("start_ts"))
    duration = (end_ts - start_ts).total_seconds() if start_ts else None
    status = payload.get("status", "failed")
    update_doc = {
        "end_ts": end_ts,
        "status": status,
        "returncode": payload.get("returncode"),
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
        "attempt": payload.get("attempt", 1),
        "completion_reason": payload.get("completion_reason"),
        "duration": duration,
    }

    worker_id = payload.get("worker_id")
    domain = payload.get("domain", "prod")
    job_id = payload.get("job_id", "")

    if existing is not None:
        existing_status = existing.get("status", "unknown")
        if existing_status in TERMINAL_STATES:
            # Run is already terminal — this is a duplicate or replayed event.
            # Do not re-apply the update or re-trigger post-run actions.
            log.warning(
                "Duplicate run_end for already-terminal run %s (status=%s → %s, job=%s); ignoring",
                run_id, existing_status, status, job_id,
            )
            return

        # Normal path: update a running/dispatched/pending run to terminal.
        res = db.job_runs.update_one(
            {"_id": run_id, "status": {"$nin": list(TERMINAL_STATES)}},
            {"$set": update_doc},
        )
        if res.matched_count == 0:
            # Race: another thread beat us to a terminal transition.
            log.warning(
                "run_end for run %s lost race to terminal transition (job=%s, status=%s); ignoring",
                run_id, job_id, status,
            )
            return
    else:
        # run_end arrived before (or without) a persisted run_start.
        # Create a minimal fallback document so the run is visible in history.
        log.warning(
            "run_end received before run_start for run %s (job=%s, status=%s); creating fallback doc",
            run_id, job_id, status,
        )
        fallback_doc = {
            "_id": run_id,
            "job_id": job_id,
            "user": payload.get("user", ""),
            "domain": domain,
            "worker_id": worker_id,
            "start_ts": _to_datetime(payload.get("start_ts")) or end_ts,
            "scheduled_ts": _to_datetime(payload.get("scheduled_ts")) or end_ts,
            **update_doc,
            "slot": payload.get("slot"),
            "retries_remaining": payload.get("retries_remaining"),
            "schedule_tick": payload.get("schedule_tick"),
            "schedule_mode": payload.get("schedule_mode"),
            "executor_type": payload.get("executor_type"),
            "queue_latency_ms": payload.get("queue_latency_ms"),
            "bypass_concurrency": bool(payload.get("bypass_concurrency", False)),
            "duration": duration,
        }
        try:
            db.job_runs.insert_one(fallback_doc)
        except DuplicateKeyError:
            # Concurrent insert (e.g. run_start arrived on another thread).
            # Re-check terminal status before proceeding to post-run actions.
            concurrent = db.job_runs.find_one({"_id": run_id}, {"status": 1})
            if (concurrent or {}).get("status") in TERMINAL_STATES:
                log.warning(
                    "run_end fallback insert lost race for run %s (job=%s); skipping post-run actions",
                    run_id, job_id,
                )
                return
            db.job_runs.update_one(
                {"_id": run_id, "status": {"$nin": list(TERMINAL_STATES)}},
                {"$set": update_doc},
            )

    if worker_id:
        append_worker_op(
            domain=domain,
            worker_id=worker_id,
            op_type="run_end",
            message=f"Finished job {job_id} ({status})",
            details={
                "run_id": run_id,
                "job_id": job_id,
                "status": status,
                "returncode": payload.get("returncode"),
                "duration": duration,
                "completion_reason": payload.get("completion_reason"),
            },
            ts=end_ts.timestamp(),
        )

    # --- Post-run actions ---
    if status == "success":
        # Trigger any dependent jobs
        _trigger_dependents(job_id, domain, db)
    elif status in {"failed", "timed_out"}:
        # Check for scheduler-level retries
        job_doc = db.job_definitions.find_one(
            {"_id": job_id},
            {
                "max_retries": 1,
                "retry_delay_seconds": 1,
                "priority": 1,
                "on_failure_webhooks": 1,
                "on_failure_email_to": 1,
                "on_failure_email_credential_ref": 1,
            },
        )
        if job_doc:
            max_retries = int(job_doc.get("max_retries", 0))
            retry_delay = int(job_doc.get("retry_delay_seconds", 0))
            retry_attempt = int(payload.get("retry_attempt", 0))
            if max_retries > 0 and retry_attempt < max_retries:
                _enqueue_job_for_retry(
                    job_id=job_id,
                    domain=domain,
                    priority=int(job_doc.get("priority", 5)),
                    retry_attempt=retry_attempt + 1,
                    delay_seconds=retry_delay,
                )
            else:
                # Terminal failure — fire webhooks
                webhooks = job_doc.get("on_failure_webhooks") or []
                stderr_text = payload.get("stderr", "") or payload.get("completion_reason", "")
                _fire_webhooks_async(webhooks, job_id, run_id, stderr_text[:_WEBHOOK_MAX_ERROR_LEN])
                email_to = job_doc.get("on_failure_email_to") or []
                email_cred_ref = str(job_doc.get("on_failure_email_credential_ref") or "").strip()
                _fire_email_alert_async(
                    db,
                    domain,
                    email_cred_ref,
                    email_to,
                    job_id,
                    run_id,
                    stderr_text[:_WEBHOOK_MAX_ERROR_LEN],
                )


def _handle_artifact_emitted(payload: Dict[str, Any]):
    """Upsert artifact record and trigger downstream jobs that subscribe to it."""
    db = get_db()
    r = get_redis()
    domain = str(payload.get("domain") or "prod").strip()
    artifact_name = str(payload.get("artifact_name") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    metadata = payload.get("metadata") or {}

    if not artifact_name:
        log.warning("artifact_emitted event missing artifact_name; skipping")
        return

    now = datetime.now(timezone.utc)
    db.artifacts.update_one(
        {"domain": domain, "name": artifact_name},
        {
            "$set": {
                "domain": domain,
                "name": artifact_name,
                "last_updated": now,
                "last_run_id": run_id,
                "last_job_id": job_id,
                "metadata": metadata,
            }
        },
        upsert=True,
    )
    log.info("Upserted artifact '%s' in domain '%s' from run %s", artifact_name, domain, run_id)

    # Find jobs that should be triggered when this artifact is updated.
    triggered_jobs = list(db.job_definitions.find(
        {"domain": domain, "triggers_on_artifacts": artifact_name, "schedule.enabled": True}
    ))
    if not triggered_jobs:
        return

    metadata_json = json.dumps(metadata)
    params = json.dumps({"HYDRA_UPSTREAM_ARTIFACT_METADATA": metadata_json})
    for dep_job in triggered_jobs:
        dep_id = dep_job["_id"]
        priority = int(dep_job.get("priority", 5))
        r.zadd(f"job_queue:{domain}:pending", {dep_id: float(priority)})
        r.hset(
            f"job_enqueue_meta:{domain}:{dep_id}",
            mapping={
                "enqueued_ts": time.time(),
                "reason": f"artifact_trigger:{artifact_name}",
                "upstream_artifact_name": artifact_name,
                "upstream_run_id": run_id,
                "upstream_job_id": job_id,
                "params": params,
            },
        )
        r.expire(f"job_enqueue_meta:{domain}:{dep_id}", 24 * 3600)
        log.info(
            "Triggered job %s due to artifact '%s' update (upstream run %s)",
            dep_id, artifact_name, run_id,
        )


def _handle_event(payload: Dict[str, Any]):
    etype = str(payload.get("type") or "").strip()
    if etype == "run_start":
        _handle_run_start(payload)
    elif etype == "run_end":
        _handle_run_end(payload)
    elif etype == "artifact_emitted":
        _handle_artifact_emitted(payload)
    else:
        log.warning("Unknown run event type: %s", etype)


def _recover_staging_events(r) -> int:
    """Move any events left in processing queues back to their source queues.

    Called once on scheduler startup to recover events that were popped but
    not fully processed before a previous crash.  Each recovered event is
    pushed to the tail of its source queue so normal ordering is preserved.
    Returns the number of events recovered.
    """
    recovered = 0
    for staging_key in list(r.scan_iter("run_events:*:processing")):
        domain = staging_key.split(":")[1]
        src_key = f"run_events:{domain}"
        while True:
            raw = r.rpoplpush(staging_key, src_key)
            if raw is None:
                break
            log.info(
                "Recovered staged run event for domain '%s' back to %s",
                domain, src_key,
            )
            recovered += 1
    if recovered:
        log.info("Recovered %d staged run event(s) after restart", recovered)
    return recovered


def run_event_loop(stop_event: threading.Event):
    r = get_redis()
    # Recover any events that were in processing queues when the scheduler
    # last stopped or crashed.  This prevents silent event loss on restart.
    _recover_staging_events(r)
    log.info("Run event loop started")
    while not stop_event.is_set():
        try:
            domains = list(r.smembers("hydra:domains") or []) or ["prod"]
            dispatched = False
            for domain in domains:
                src_key = f"run_events:{domain}"
                staging_key = f"run_events:{domain}:processing"
                # Atomically move one event from the source queue to the
                # per-domain staging queue.  If the scheduler crashes after
                # this point but before the LREM below, the event remains in
                # the staging queue and will be recovered on the next startup
                # by _recover_staging_events().
                raw = r.rpoplpush(src_key, staging_key)
                if raw is None:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    log.warning(
                        "Skipping malformed run event payload from %s", src_key
                    )
                    r.lrem(staging_key, 1, raw)
                    dispatched = True
                    continue
                try:
                    _handle_event(payload)
                except Exception as exc:
                    log.exception("Error processing run event from %s: %s", src_key, exc)
                finally:
                    # Remove the successfully-consumed (or unprocessable) raw
                    # event from the staging queue.  Event handlers are
                    # idempotent, so a duplicate delivery on restart is safe.
                    r.lrem(staging_key, 1, raw)
                dispatched = True
                break  # Process one event per loop tick; re-check all domains next tick
            if not dispatched:
                # No events across any domain — sleep briefly to avoid spin.
                time.sleep(0.1)
        except Exception as exc:
            log.exception("Error in run event loop: %s", exc)
            time.sleep(1)
