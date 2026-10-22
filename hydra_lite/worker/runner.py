"""Execute one claimed run by wrapping the main edition's Redis-free executor."""

from __future__ import annotations

import logging
import threading
import time

from worker.executor import execute_job
from worker.utils.completion import evaluate_completion, evaluate_file_criteria
from worker.utils.params import inject_params

from ..lifecycle import Lifecycle
from ..logs import LogStore
from ..store import Store
from ..store.store import now_utc

log = logging.getLogger("hydra_lite.runner")


def execute_run(store: Store, logs: LogStore, lifecycle: Lifecycle, run: dict, job: dict, kill_event: threading.Event) -> str:
    """Run ``run`` to completion, recording logs and the terminal state. Returns the final status."""
    run_id = run["id"]
    month = now_utc().isoformat()
    runlog = logs.open_writer(run_id, month)
    try:
        store.start_run(run_id, log_path=str(runlog.base))
        job = inject_params(job, run.get("params"))
        attempts = int(job.get("retries", 0) or 0) + 1
        success, reason, rc, attempts_used = False, "", 1, 0
        timed_out: dict = {}
        for attempt in range(attempts):
            timed_out = {}
            attempts_used += 1
            started = time.time()
            rc, stdout, stderr = execute_job(
                job,
                log_callback_out=lambda text: runlog.write("out", text),
                log_callback_err=lambda text: runlog.write("err", text),
                kill_event=kill_event,
                timings={},
                timed_out_holder=timed_out,
            )
            success, reason = evaluate_completion(job, rc, stdout, stderr)
            if success:
                file_ok, file_reason = evaluate_file_criteria(job, started)
                if not file_ok:
                    success, reason = False, file_reason
                    runlog.write("err", f"[hydra] file validation failed: {file_reason}\n")
            if success or kill_event.is_set():
                break
            if attempt + 1 < attempts:
                store.add_event(run_id, "retry", {"attempt": attempt + 1, "reason": reason})
        event_type = None
        kill_reason = getattr(kill_event, "reason", None)
        if kill_event.is_set() and not success:
            if kill_reason == "timeout":
                status, reason = "timed_out", "killed by the daemon after exceeding the job timeout"
            else:
                status, reason, event_type = "failed", "killed by request", "killed"
        elif success:
            status = "success"
        elif timed_out.get("timed_out"):
            status = "timed_out"
        else:
            status = "failed"
        lifecycle.finalize(run_id, status, returncode=rc, reason=reason, attempt=attempts_used, event_type=event_type)
        return status
    except Exception as exc:  # keep the worker alive; record why the run failed
        log.exception("run %s crashed", run_id)
        runlog.write("err", f"[hydra] run crashed: {exc}\n")
        lifecycle.finalize(run_id, "failed", returncode=1, reason=f"internal error: {exc}")
        return "failed"
    finally:
        runlog.close()
