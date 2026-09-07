import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from redis.exceptions import RedisError

# Capture process start time before any significant work occurs so that
# worker_startup_duration_ms can be accurately recorded at registration.
_PROCESS_START_TS: float = time.time()

from .config import (
    get_allowed_users,
    get_domain,
    get_domain_token,
    get_initial_state,
    get_max_concurrency,
    get_tags,
    get_worker_id,
)
from .executor import execute_job
from .redis_client import get_redis
from .utils.completion import evaluate_completion, evaluate_file_criteria
from .utils.concurrency import add_active_job, incr_running, remove_active_job
from .utils.heartbeat import start_heartbeat


def append_worker_op(r, domain: str, worker_id: str, op_type: str, message: str, details: dict | None = None):
    event = {
        "ts": time.time(),
        "type": op_type,
        "message": message,
        "details": details or {},
    }
    key = f"worker_ops:{domain}:{worker_id}"
    r.rpush(key, json.dumps(event))
    r.ltrim(key, -1000, -1)
    r.expire(key, 7 * 24 * 3600)


def register_worker(worker_id: str, max_concurrency: int):
    r = get_redis()
    import getpass
    import platform
    import socket

    from .runtime import _detect_capabilities, _detect_shells

    hostname = socket.gethostname()
    try:
        ip_addr = socket.gethostbyname(hostname)
    except Exception:
        ip_addr = ""
    subnet = ".".join(ip_addr.split(".")[:3]) if ip_addr else ""
    import pathlib
    _in_docker = pathlib.Path("/.dockerenv").exists()
    _default_deployment_type = "docker" if _in_docker else "standalone"
    deployment_type = os.getenv("DEPLOYMENT_TYPE", _default_deployment_type)
    domain_token = get_domain_token()
    domain = get_domain()
    worker_key = f"workers:{domain}:{worker_id}"
    is_restart = bool(r.exists(worker_key))

    shells = _detect_shells()
    capabilities = _detect_capabilities()
    startup_duration_ms = round((time.time() - _PROCESS_START_TS) * 1000, 2)

    meta = {
        "os": platform.system().lower(),
        "domain": domain,
        "tags": ",".join(get_tags()),
        "allowed_users": ",".join(get_allowed_users()),
        "max_concurrency": max_concurrency,
        "current_running": 0,
        "status": "online",
        "state": get_initial_state(),
        "cpu_count": os.cpu_count() or 1,
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
        "hostname": hostname,
        "ip": ip_addr,
        "subnet": subnet,
        "deployment_type": deployment_type,
        "run_user": getpass.getuser(),
        "shells": ",".join(shells),
        "capabilities": ",".join(capabilities),
        "domain_token_hash": __import__("hashlib").sha256(domain_token.encode()).hexdigest(),
        "startup_duration_ms": startup_duration_ms,
    }
    r.hset(worker_key, mapping=meta)
    append_worker_op(
        r=r,
        domain=domain,
        worker_id=worker_id,
        op_type="restart" if is_restart else "start",
        message="Worker process registered" if not is_restart else "Worker process restarted and re-registered",
        details={
            "max_concurrency": max_concurrency,
            "state": meta.get("state"),
            "hostname": hostname,
            "run_user": meta.get("run_user"),
            "pid": os.getpid(),
            "startup_duration_ms": startup_duration_ms,
        },
    )


def worker_main():
    r = get_redis()
    worker_id = get_worker_id()
    max_concurrency = get_max_concurrency()
    domain = get_domain()
    register_worker(worker_id, max_concurrency)

    active_jobs = set()
    active_jobs_lock = threading.Lock()
    # Maps run_id -> threading.Event; set to kill the running subprocess
    active_kill_events: dict = {}
    active_kill_lock = threading.Lock()

    def get_active_jobs():
        with active_jobs_lock:
            return list(active_jobs)

    start_heartbeat(
        worker_id,
        get_active_jobs,
        refresh_registration=lambda: register_worker(worker_id, max_concurrency),
    )

    executor = ThreadPoolExecutor(max_workers=max_concurrency)

    def publish_run_event(event: dict):
        r.rpush(f"run_events:{domain}", json.dumps(event))
        r.expire(f"run_events:{domain}", 24 * 3600)

    def _kill_listener():
        """Subscribe to job_kill:{domain} and set the kill event for matching run_ids.

        Restarts automatically on any Redis/connection error with exponential
        backoff (2 s → 4 s → … → 60 s) so that transient disconnects recover
        quickly while persistent auth/config failures don't spam the logs.
        """
        _BACKOFF_INITIAL = 2.0
        _BACKOFF_MAX = 60.0
        backoff = _BACKOFF_INITIAL
        while True:
            pubsub = None
            try:
                sub_r = get_redis()
                pubsub = sub_r.pubsub()
                pubsub.subscribe(f"job_kill:{domain}")
                # Successful connection — reset backoff.
                backoff = _BACKOFF_INITIAL
                for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    raw = msg.get("data") or b""
                    run_id = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()
                    if not run_id:
                        continue
                    with active_kill_lock:
                        evt = active_kill_events.get(run_id)
                    if evt is not None:
                        evt.set()
            except Exception as exc:
                print(f"Worker {worker_id} kill listener error: {exc}; retrying in {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
            finally:
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:
                        pass

    threading.Thread(target=_kill_listener, daemon=True).start()

    def run_job(envelope: dict, bypass_override: bool = False):
        job = envelope.get("job") or {}
        job_id = envelope.get("job_id") or job.get("_id") or job.get("id")
        if not job_id:
            return
        run_id = None
        _incremented = False
        _active_job_added = False
        _active_jobs_added = False
        try:
            bypass_concurrency = bool(job.get("bypass_concurrency", False) or bypass_override)
            with active_jobs_lock:
                active_jobs.add(job_id)
            _active_jobs_added = True
            slot_position = incr_running(worker_id, +1) - 1
            _incremented = True
            add_active_job(worker_id, job_id)
            _active_job_added = True
            run_id = uuid.uuid4().hex
            retries_remaining = int(job.get("retries", 0))
            retry_attempt = int(envelope.get("retry_attempt", 0))
            started_ts = time.time()
            enqueued_ts = envelope.get("enqueued_ts")
            try:
                queue_latency_ms = max(0.0, (started_ts - float(enqueued_ts)) * 1000.0) if enqueued_ts is not None else None
            except Exception:
                queue_latency_ms = None

            r.hset(
                f"job_running:{domain}:{job_id}",
                mapping={
                    "worker_id": worker_id,
                    "heartbeat": started_ts,
                    "user": job.get("user", ""),
                    "domain": domain,
                    "run_id": run_id,
                },
            )
            publish_run_event(
                {
                    "type": "run_start",
                    "run_id": run_id,
                    "job_id": job_id,
                    "user": job.get("user", ""),
                    "domain": domain,
                    "worker_id": worker_id,
                    "start_ts": started_ts,
                    "scheduled_ts": envelope.get("dispatch_ts") or started_ts,
                    "slot": slot_position,
                    "attempt": 1,
                    "retries_remaining": retries_remaining,
                    "schedule_tick": (job.get("schedule") or {}).get("next_run_at"),
                    "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
                    "executor_type": (job.get("executor") or {}).get("type", "shell"),
                    "queue_latency_ms": queue_latency_ms,
                    "bypass_concurrency": bypass_concurrency,
                }
            )
            append_worker_op(
                r=r,
                domain=domain,
                worker_id=worker_id,
                op_type="run_exec",
                message=f"Executing job {job_id}",
                details={"run_id": run_id, "job_id": job_id, "slot": slot_position},
            )

            def stream_log(kind: str, chunk: str):
                if not chunk:
                    return
                payload = {
                    "run_id": run_id,
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "domain": domain,
                    "ts": time.time(),
                    "text": chunk,
                    "stream": kind,
                }
                data = json.dumps(payload)
                channel = f"log_stream:{domain}:{run_id}"
                history_key = f"log_stream:{domain}:{run_id}:history"
                r.rpush(history_key, data)
                r.ltrim(history_key, -400, -1)
                r.publish(channel, data)
                r.expire(history_key, 3600)
                r.expire(channel, 3600)

            _ARTIFACT_PREFIX = "__HYDRA_ARTIFACT__:"

            def handle_stdout(text: str):
                stripped = text.strip()
                if stripped.startswith(_ARTIFACT_PREFIX):
                    raw_json = stripped[len(_ARTIFACT_PREFIX):].strip()
                    try:
                        artifact_payload = json.loads(raw_json)
                        artifact_name = str(artifact_payload.get("name") or "").strip()
                        metadata = artifact_payload.get("metadata") or {}
                        if artifact_name:
                            publish_run_event({
                                "type": "artifact_emitted",
                                "run_id": run_id,
                                "job_id": job_id,
                                "domain": domain,
                                "artifact_name": artifact_name,
                                "metadata": metadata,
                            })
                    except Exception:
                        stream_log("stdout", text)
                    return
                stream_log("stdout", text)

            # Inject runtime params as environment variables
            params = envelope.get("params") or {}
            if params:
                job = dict(job)
                exec_dict = dict(job.get("executor") or {})
                env_dict = dict(exec_dict.get("env") or {})
                env_dict.update({k: str(v) for k, v in params.items()})
                exec_dict["env"] = env_dict
                job["executor"] = exec_dict

            # Register kill event for this run
            kill_event = threading.Event()
            with active_kill_lock:
                active_kill_events[run_id] = kill_event

            # Execute with retries
            attempts = int(job.get("retries", 0)) + 1
            rc = 1
            stdout = ""
            stderr = ""
            attempts_used = 0
            last_reason = ""
            success = False
            timings: dict = {}
            first_attempt = True
            timed_out_holder: dict = {}
            for _ in range(max(1, attempts)):
                run_start_time = time.time()
                attempt_timings: dict = {}
                timed_out_holder = {}
                rc, stdout, stderr = execute_job(
                    job,
                    log_callback_out=handle_stdout,
                    log_callback_err=lambda text: stream_log("stderr", text),
                    kill_event=kill_event,
                    timings=attempt_timings,
                    timed_out_holder=timed_out_holder,
                )
                # Capture timings from the first attempt only
                if first_attempt:
                    timings = attempt_timings
                    first_attempt = False
                attempts_used += 1
                success, last_reason = evaluate_completion(job, rc, stdout, stderr)
                if success:
                    file_ok, file_reason = evaluate_file_criteria(job, run_start_time)
                    if not file_ok:
                        success = False
                        last_reason = file_reason
                        stream_log("stderr", f"[hydra] file validation failed: {file_reason}")
                if success:
                    break

            end_ts = time.time()
            # rc == 124 alone isn't reliable: a normally-exiting command can
            # legitimately return 124 for its own reasons, which would
            # otherwise be misreported as a timeout (and become eligible for
            # scheduler-level retry, potentially rerunning non-idempotent
            # work). timed_out_holder is set explicitly by the subprocess
            # layer only when a wait actually timed out.
            status = "success" if success else ("timed_out" if timed_out_holder.get("timed_out") else "failed")
            publish_run_event(
                {
                    "type": "run_end",
                    "run_id": run_id,
                    "job_id": job_id,
                    "user": job.get("user", ""),
                    "domain": domain,
                    "worker_id": worker_id,
                    "status": status,
                    "returncode": rc,
                    "stdout": stdout,
                    "stderr": stderr,
                    "attempt": attempts_used,
                    "completion_reason": last_reason or "criteria not met",
                    "end_ts": end_ts,
                    "slot": slot_position,
                    "retries_remaining": retries_remaining,
                    "retry_attempt": retry_attempt,
                    "schedule_tick": (job.get("schedule") or {}).get("next_run_at"),
                    "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
                    "executor_type": (job.get("executor") or {}).get("type", "shell"),
                    "queue_latency_ms": queue_latency_ms,
                    "bypass_concurrency": bypass_concurrency,
                    "start_ts": started_ts,
                    "scheduled_ts": envelope.get("dispatch_ts") or started_ts,
                    "total_run_ms": round((end_ts - started_ts) * 1000, 2),
                    "source_fetch_ms": timings.get("source_fetch_ms"),
                    "env_prep_ms": timings.get("env_prep_ms"),
                }
            )
            append_worker_op(
                r=r,
                domain=domain,
                worker_id=worker_id,
                op_type="run_result",
                message=f"Job {job_id} completed with status {status}",
                details={
                    "run_id": run_id,
                    "job_id": job_id,
                    "status": status,
                    "returncode": rc,
                    "attempt": attempts_used,
                    "completion_reason": last_reason or "criteria not met",
                },
            )
        finally:
            if run_id is not None:
                with active_kill_lock:
                    active_kill_events.pop(run_id, None)
            r.delete(f"job_running:{domain}:{job_id}")
            if _active_job_added:
                remove_active_job(worker_id, job_id)
            if _incremented:
                incr_running(worker_id, -1)
            if _active_jobs_added:
                with active_jobs_lock:
                    active_jobs.discard(job_id)

    print(f"Worker {worker_id} starting with max_concurrency={max_concurrency}")
    while True:
        try:
            item = r.blpop([f"job_queue:{domain}:{worker_id}"], timeout=2)
        except RedisError as exc:
            # Keep worker alive across transient Redis disconnects/restarts.
            print(f"Worker {worker_id} Redis error while polling queue: {exc}")
            time.sleep(1)
            continue
        if not item:
            continue
        _, raw_payload = item
        try:
            envelope = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            # A BLPOP is destructive, so retain malformed payloads for operator
            # inspection instead of silently losing them.
            dead_letter_key = f"job_queue:{domain}:dead_letter"
            r.rpush(dead_letter_key, raw_payload)
            r.expire(dead_letter_key, 7 * 24 * 3600)
            print(f"Malformed queue payload moved to {dead_letter_key}")
            continue
        bypass_concurrency = bool(((envelope.get("job") or {}).get("bypass_concurrency", False)))
        if bypass_concurrency:
            threading.Thread(target=run_job, args=(envelope, True), daemon=True).start()
        else:
            executor.submit(run_job, envelope, False)


if __name__ == "__main__":
    worker_main()
