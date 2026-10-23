"""Execute one claimed run by wrapping the main edition's Redis-free executor.

The same ``execute_run`` serves both worker flavours; they differ only in the *sink* that receives the run's
lifecycle (local SQLite for the in-process pool, HTTP for subprocess workers), so the two paths cannot diverge.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Protocol

from worker.executor import execute_job
from worker.utils.completion import evaluate_completion, evaluate_file_criteria
from worker.utils.params import inject_params

from ..lifecycle import Lifecycle
from ..logs import LogStore
from ..store import Store
from ..store.store import now_utc

log = logging.getLogger("hydra_lite.runner")


class RunSink(Protocol):
    def start(self, run: dict, job: dict) -> None: ...

    def log(self, stream: str, text: str) -> None: ...

    def retrying(self, attempt: int, reason: str) -> None: ...

    def finish(
        self,
        status: str,
        returncode: Optional[int],
        reason: Optional[str],
        attempts: int,
        event_type: Optional[str],
        timings: dict,
    ) -> None: ...

    def close(self) -> None: ...


class LocalSink:
    """Writes straight to the daemon's store, log files and lifecycle (in-process workers)."""

    def __init__(self, store: Store, logs: LogStore, lifecycle: Lifecycle, worker_id: str = "local"):
        self.store, self.logs, self.lifecycle, self.worker_id = store, logs, lifecycle, worker_id
        self._run_id = ""
        self._log = None

    def start(self, run: dict, job: dict) -> None:
        self._run_id = run["id"]
        self._log = self.logs.open_writer(self._run_id, now_utc().isoformat())
        self.store.start_run(self._run_id, log_path=str(self._log.base))

    def log(self, stream: str, text: str) -> None:
        if self._log:
            self._log.write("out" if stream == "stdout" else "err", text)

    def retrying(self, attempt: int, reason: str) -> None:
        self.store.add_event(self._run_id, "retry", {"attempt": attempt, "reason": reason})

    def finish(self, status, returncode, reason, attempts, event_type, timings) -> None:
        self.lifecycle.finalize(
            self._run_id, status, returncode=returncode, reason=reason, attempt=attempts, event_type=event_type, timings=timings
        )

    def close(self) -> None:
        if self._log:
            self._log.close()


class _Tails:
    """Forwards streamed output to the sink while remembering the last bytes, to spot text that was never streamed."""

    KEEP = 8192

    def __init__(self, sink: "RunSink"):
        self.sink = sink
        self.tail = {"stdout": "", "stderr": ""}

    def write(self, stream: str, text: str) -> None:
        self.sink.log(stream, text)
        self.tail[stream] = (self.tail[stream] + text)[-self.KEEP :]

    def flush_unstreamed(self, stdout: str, stderr: str) -> None:
        for stream, text in (("stdout", stdout), ("stderr", stderr)):
            text = (text or "").strip()
            if text and text[-200:] not in self.tail[stream]:
                self.sink.log(stream, text + "\n")


def execute_run(sink: RunSink, run: dict, job: dict, kill_event: threading.Event) -> str:
    """Run ``run`` to completion through ``sink``. Returns the final status."""
    run_id = run["id"]
    try:
        sink.start(run, job)
        job = inject_params(job, run.get("params"))
        attempts = int(job.get("retries", 0) or 0) + 1
        success, reason, rc, attempts_used = False, "", 1, 0
        timed_out: dict = {}
        timings: dict = {}
        for attempt in range(attempts):
            timed_out = {}
            attempts_used += 1
            started = time.time()
            attempt_timings: dict = {}
            tails = _Tails(sink)
            rc, stdout, stderr = execute_job(
                job,
                log_callback_out=lambda text: tails.write("stdout", text),
                log_callback_err=lambda text: tails.write("stderr", text),
                kill_event=kill_event,
                timings=attempt_timings,
                timed_out_holder=timed_out,
            )
            # Some executors (sensor, http, source/env failures) report a message only in their return value and never
            # stream it; the full edition carries that text in run_end, lite keeps logs as files, so emit what is missing.
            tails.flush_unstreamed(stdout, stderr)
            if attempt == 0:
                timings = attempt_timings
            success, reason = evaluate_completion(job, rc, stdout, stderr)
            if success:
                file_ok, file_reason = evaluate_file_criteria(job, started)
                if not file_ok:
                    success, reason = False, file_reason
                    sink.log("stderr", f"[hydra] file validation failed: {file_reason}\n")
            if success or kill_event.is_set():
                break
            if attempt + 1 < attempts:
                sink.retrying(attempt + 1, reason)
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
        sink.finish(status, rc, reason, attempts_used, event_type, timings)
        return status
    except Exception as exc:  # keep the worker alive; record why the run failed
        log.exception("run %s crashed", run_id)
        try:
            sink.log("stderr", f"[hydra] run crashed: {exc}\n")
            sink.finish("failed", 1, f"internal error: {exc}", 0, None, {})
        except Exception:
            log.exception("could not report crash of run %s", run_id)
        return "failed"
    finally:
        sink.close()
