import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .mongo_client import get_db
from .redis_client import get_redis
from .config import (
    get_worker_id,
    get_tags,
    get_allowed_users,
    get_max_concurrency,
    get_queues,
    get_initial_state,
    get_domain,
    get_domain_token,
)
from .utils.heartbeat import start_heartbeat
from .utils.concurrency import incr_running, add_active_job, remove_active_job
from .utils.completion import evaluate_completion
from .executor import execute_job, record_run_start, record_run_end


def register_worker(worker_id: str, max_concurrency: int):
    r = get_redis()
    import platform
    import socket
    import getpass

    hostname = socket.gethostname()
    try:
        ip_addr = socket.gethostbyname(hostname)
    except Exception:
        ip_addr = ""
    subnet = ".".join(ip_addr.split(".")[:3]) if ip_addr else ""
    deployment_type = os.getenv("DEPLOYMENT_TYPE", "docker")
    domain_token = get_domain_token()

    meta = {
        "os": platform.system().lower(),
        "domain": get_domain(),
        "tags": ",".join(get_tags()),
        "allowed_users": ",".join(get_allowed_users()),
        "queues": ",".join(get_queues()),
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
        "domain_token_hash": __import__("hashlib").sha256(domain_token.encode()).hexdigest(),
    }
    r.sadd("hydra:domains", get_domain())
    r.hset(f"workers:{get_domain()}:{worker_id}", mapping=meta)


def worker_main():
    r = get_redis()
    db = get_db()
    worker_id = get_worker_id()
    max_concurrency = get_max_concurrency()
    register_worker(worker_id, max_concurrency)

    active_jobs = set()
    active_jobs_lock = threading.Lock()

    def get_active_jobs():
        with active_jobs_lock:
            return list(active_jobs)

    start_heartbeat(worker_id, get_active_jobs)

    executor = ThreadPoolExecutor(max_workers=max_concurrency)

    def run_job(job_id: str):
        try:
            job = db.job_definitions.find_one({"_id": job_id})
            if not job:
                return
            with active_jobs_lock:
                active_jobs.add(job_id)
            slot_position = incr_running(worker_id, +1) - 1
            add_active_job(worker_id, job_id)
            r.hset(
                f"job_running:{get_domain()}:{job_id}",
                mapping={"worker_id": worker_id, "heartbeat": time.time(), "user": job.get("user", ""), "domain": get_domain()},
            )

            # Create/mark run start
            retries_remaining = int(job.get("retries", 0))
            run_id = record_run_start(job, worker_id, slot_position, retries_remaining)

            def stream_log(kind: str, chunk: str):
                if not chunk:
                    return
                payload = {
                    "run_id": run_id,
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "domain": get_domain(),
                    "ts": time.time(),
                    "text": chunk,
                    "stream": kind,
                }
                import json

                data = json.dumps(payload)
                channel = f"log_stream:{run_id}"
                history_key = f"log_stream:{run_id}:history"
                r.rpush(history_key, data)
                r.ltrim(history_key, -400, -1)
                r.publish(channel, data)
                r.expire(history_key, 3600)
                r.expire(channel, 3600)

            # Execute with retries
            attempts = int(job.get("retries", 0)) + 1
            rc = 1
            stdout = ""
            stderr = ""
            attempts_used = 0
            last_reason = ""
            success = False
            for _ in range(max(1, attempts)):
                rc, stdout, stderr = execute_job(
                    job,
                    log_callback_out=lambda text: stream_log("stdout", text),
                    log_callback_err=lambda text: stream_log("stderr", text),
                )
                attempts_used += 1
                success, last_reason = evaluate_completion(job, rc, stdout, stderr)
                if success:
                    break

            status = "success" if success else "failed"
            record_run_end(run_id, status, rc, stdout, stderr, attempts_used, last_reason or "criteria not met")
        finally:
            r.delete(f"job_running:{get_domain()}:{job_id}")
            remove_active_job(worker_id, job_id)
            incr_running(worker_id, -1)
            with active_jobs_lock:
                active_jobs.discard(job_id)

    print(f"Worker {worker_id} starting with max_concurrency={max_concurrency}")
    while True:
        item = r.blpop([f"job_queue:{get_domain()}:{worker_id}"], timeout=2)
        if not item:
            continue
        _, job_id = item
        executor.submit(run_job, job_id)


if __name__ == "__main__":
    worker_main()
