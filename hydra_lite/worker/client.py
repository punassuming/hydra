"""Subprocess worker: claims runs from the daemon over loopback HTTP and executes them.

Run through ``python -m hydra_lite.worker``. Configuration uses the environment variable names the full
edition's worker reads (``WORKER_ID``, ``MAX_CONCURRENCY``, ``WORKER_TAGS``, ``ALLOWED_USERS``,
``WORKER_SHUTDOWN_GRACE_SECONDS``) plus ``HYDRA_API_URL`` / ``HYDRA_TOKEN`` for the daemon.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from typing import Optional

from cli._client import APIError, HydraClient

from .killevent import KillEvent
from .meta import build_worker_meta
from .runner import execute_run

log = logging.getLogger("hydra_lite.worker.client")

HEARTBEAT_SECONDS = 2.0
CLAIM_WAIT_SECONDS = 15.0
BACKOFF_FLOOR, BACKOFF_CAP = 2.0, 60.0  # same shape as worker/worker.py's kill-listener reconnect
FLUSH_SECONDS = 0.5
BYPASS_BATCH = 8  # most bypass runs claimed per poll when SCHEDULER_BYPASS_MAX_EXTRA is unlimited
FLUSH_BYTES = 64 * 1024
MAX_BUFFER_BYTES = 8 * 1024 * 1024  # backpressure: producers block rather than grow without bound


class LogShipper:
    """Batches output chunks and posts them to ``/internal/logs`` from a background thread."""

    def __init__(self, client: HydraClient):
        self.client = client
        self._chunks: list[dict] = []
        self._bytes = 0
        self._cond = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="hydra-log-shipper", daemon=True)
        self._thread.start()

    def add(self, run_id: str, stream: str, text: str) -> None:
        if not text:
            return
        with self._cond:
            while self._bytes > MAX_BUFFER_BYTES and not self._stop:
                self._cond.wait(0.1)
            if self._chunks and self._chunks[-1]["run_id"] == run_id and self._chunks[-1]["stream"] == stream:
                self._chunks[-1]["text"] += text
            else:
                self._chunks.append({"run_id": run_id, "stream": stream, "text": text})
            self._bytes += len(text)
            if self._bytes >= FLUSH_BYTES:
                self._cond.notify_all()

    def flush(self) -> None:
        """Send everything buffered so far (called before a run reports completion)."""
        with self._cond:
            chunks, self._chunks, self._bytes = self._chunks, [], 0
            self._cond.notify_all()
        self._send(chunks)

    def _send(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        delay = BACKOFF_FLOOR
        for _ in range(5):
            try:
                self.client.request("POST", "/internal/logs", body={"chunks": chunks})
                return
            except APIError as exc:
                if exc.status is not None and exc.status < 500:
                    log.warning("daemon rejected log chunks: %s", exc)
                    return
                time.sleep(delay)
                delay = min(delay * 2, BACKOFF_CAP)
        log.error("dropping %d log chunk(s) after repeated failures", len(chunks))

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait(FLUSH_SECONDS)
                stopping = self._stop
            self.flush()
            if stopping:
                return

    def close(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._thread.join(timeout=10)
        self.flush()


class HttpSink:
    """Reports one run's lifecycle to the daemon using the full edition's event payload shapes."""

    def __init__(self, worker: "HttpWorker", envelope: dict):
        self.worker = worker
        self.envelope = envelope
        self.run_id = envelope["run_id"]
        self.job = envelope["job"]
        self.started = time.time()

    def _base(self, kind: str) -> dict:
        job = self.job
        return {
            "type": kind,
            "run_id": self.run_id,
            "job_id": self.envelope["job_id"],
            "user": job.get("user", ""),
            "domain": "prod",
            "worker_id": self.worker.worker_id,
            "executor_type": (job.get("executor") or {}).get("type", "shell"),
            "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
            "retry_attempt": self.envelope.get("retry_attempt", 0),
            "queue_latency_ms": self.envelope.get("queue_latency_ms"),
            "bypass_concurrency": bool(job.get("bypass_concurrency", False)),
        }

    def start(self, run: dict, job: dict) -> None:
        self.started = time.time()
        result = self.worker.post_event({**self._base("run_start"), "start_ts": self.started, "attempt": 1})
        if not result.get("ok", True):
            raise RuntimeError(f"daemon refused run_start: {result.get('reason')}")

    def log(self, stream: str, text: str) -> None:
        self.worker.shipper.add(self.run_id, stream, text)

    def artifact(self, name: str, metadata: dict) -> None:
        self.worker.post_event({**self._base("artifact_emitted"), "artifact_name": name, "metadata": metadata}, required=False)

    def retrying(self, attempt: int, reason: str) -> None:
        self.worker.post_event({**self._base("run_retry"), "attempt": attempt, "reason": reason}, required=False)

    def finish(self, status, returncode, reason, attempts, event_type, timings) -> None:
        self.worker.shipper.flush()
        end = time.time()
        payload = {
            **self._base("run_end"),
            "status": status,
            "returncode": returncode,
            "attempt": attempts,
            "completion_reason": reason or "criteria not met",
            "end_ts": end,
            "start_ts": self.started,
            "total_run_ms": round((end - self.started) * 1000, 2),
            "source_fetch_ms": timings.get("source_fetch_ms"),
            "env_prep_ms": timings.get("env_prep_ms"),
        }
        if event_type:
            payload["event_type"] = event_type
        self.worker.post_event(payload)

    def close(self) -> None:
        pass


class HttpWorker:
    def __init__(self, base_url: str, token: str, worker_id: str, max_concurrency: int = 2, tags: Optional[list] = None):
        self.client = HydraClient(base_url, token=token, timeout=CLAIM_WAIT_SECONDS + 15)
        self.worker_id = worker_id
        self.max_concurrency = max(1, max_concurrency)
        self.tags = tags or []
        self.shipper = LogShipper(HydraClient(base_url, token=token, timeout=30))
        self.stop = threading.Event()  # stop claiming new work and drain
        self.halt = threading.Event()  # the process is about to exit: stop heartbeating too
        self.state = "online"
        self._active: dict[str, KillEvent] = {}
        self._lock = threading.Lock()
        self._registered = threading.Event()
        self._last_contact = time.monotonic()
        self._warned_bypass = False
        self.orphan_exit_seconds = float(os.getenv("WORKER_ORPHAN_EXIT_SECONDS", "120"))

    # ---------------------------------------------------------------- transport
    def _retrying(self, fn, what: str):
        delay = BACKOFF_FLOOR
        while not self.stop.is_set():
            try:
                return fn()
            except APIError as exc:
                if exc.status is not None and exc.status < 500 and exc.status != 404:
                    raise
                if exc.status == 404:  # daemon forgot us (restart/prune): register again
                    self._register()
                log.warning("%s failed (%s); retrying in %.0fs", what, exc, delay)
                self.stop.wait(delay)
                delay = min(delay * 2, BACKOFF_CAP)
        raise RuntimeError("worker is stopping")

    def post_event(self, payload: dict, required: bool = True) -> dict:
        if not required:
            try:
                return self.client.request("POST", "/internal/events", body=payload) or {}
            except APIError as exc:
                log.warning("event %s not delivered: %s", payload.get("type"), exc)
                return {}
        # run_end must not be lost to a daemon restart: keep trying well past the heartbeat TTL.
        delay, deadline = BACKOFF_FLOOR, time.monotonic() + 300
        while True:
            try:
                return self.client.request("POST", "/internal/events", body=payload) or {}
            except APIError as exc:
                if (exc.status is not None and exc.status < 500) or time.monotonic() > deadline:
                    log.error("event %s for run %s not delivered: %s", payload.get("type"), payload.get("run_id"), exc)
                    if payload.get("type") == "run_start":
                        raise
                    return {}
                time.sleep(delay)
                delay = min(delay * 2, BACKOFF_CAP)

    # ------------------------------------------------------------ registration
    def _register(self) -> None:
        reply = self.client.request(
            "POST",
            "/internal/register",
            body={"worker_id": self.worker_id, "max_concurrency": self.max_concurrency, "meta": build_worker_meta(self.tags)},
        )
        self.state = (reply or {}).get("state", "online")
        self._registered.set()

    # ------------------------------------------------------------------- loops
    def _heartbeat_loop(self) -> None:
        while not self.halt.wait(HEARTBEAT_SECONDS):  # keeps beating while draining so the reaper leaves in-flight runs alone
            with self._lock:
                running = list(self._active)
            try:
                reply = (
                    self.client.request(
                        "POST", "/internal/heartbeat", body={"worker_id": self.worker_id, "running_run_ids": running}
                    )
                    or {}
                )
            except APIError as exc:
                if exc.status == 404:
                    try:
                        self._register()
                    except APIError:
                        pass
                if time.monotonic() - self._last_contact > self.orphan_exit_seconds:
                    log.error("daemon unreachable for %.0fs; this worker is orphaned, shutting down", self.orphan_exit_seconds)
                    self.stop.set()
                continue  # transient: the next beat retries; the daemon's reaper owns the consequences
            self._last_contact = time.monotonic()
            self.state = reply.get("state", self.state)
            for order in reply.get("kill", []):
                with self._lock:
                    event = self._active.get(order["run_id"])
                if event is not None and not event.is_set():
                    event.reason = order.get("reason", "request")
                    event.set()
            if reply.get("stop"):
                log.info("daemon asked this worker to stop")
                self.stop.set()

    def _run_envelope(self, envelope: dict) -> None:
        run_id = envelope["run_id"]
        kill_event = KillEvent()
        with self._lock:
            self._active[run_id] = kill_event
        try:
            run = {"id": run_id, "params": envelope.get("params") or {}}
            execute_run(HttpSink(self, envelope), run, envelope["job"], kill_event)
        except Exception:
            log.exception("run %s failed in the worker", run_id)
        finally:
            with self._lock:
                self._active.pop(run_id, None)

    def run(self) -> None:
        self._retrying(self._register, "registration")
        threading.Thread(target=self._heartbeat_loop, name="hydra-worker-heartbeat", daemon=True).start()
        threads: list[threading.Thread] = []
        while not self.stop.is_set():
            with self._lock:
                active = len(self._active)
            free = self.max_concurrency - active
            extra_room = self._bypass_room(active)
            if (free <= 0 and extra_room <= 0) or self.state != "online":
                self.stop.wait(0.2)
                continue
            # While full only bypass jobs can be taken, so poll briefly: a normal slot may free up at any moment.
            wait = CLAIM_WAIT_SECONDS if free > 0 else 1.0
            try:
                reply = self.client.request(
                    "POST",
                    "/internal/claim",
                    body={"worker_id": self.worker_id, "capacity": max(free, 0), "bypass": extra_room, "wait": wait},
                )
            except APIError as exc:
                if exc.status == 404:
                    self._retrying(self._register, "registration")
                else:
                    log.warning("claim failed (%s)", exc)
                    self.stop.wait(BACKOFF_FLOOR)
                continue
            for envelope in (reply or {}).get("runs", []):
                with self._lock:
                    self._active[envelope["run_id"]] = KillEvent()  # reserve the slot before the thread starts
                t = threading.Thread(
                    target=self._start_reserved, args=(envelope,), name=f"hydra-run-{envelope['run_id'][:8]}", daemon=True
                )
                t.start()
                threads.append(t)
            threads = [t for t in threads if t.is_alive()]
        self._drain(threads)

    def _bypass_room(self, active: int) -> int:
        """How many bypass_concurrency runs may start now (SCHEDULER_BYPASS_MAX_EXTRA caps the extras; 0 = unlimited)."""
        cap = int(os.getenv("SCHEDULER_BYPASS_MAX_EXTRA", "0") or 0)
        extra_in_use = max(0, active - self.max_concurrency)
        room = BYPASS_BATCH if cap <= 0 else max(0, cap - extra_in_use)
        if room > 0 and active >= self.max_concurrency and not self._warned_bypass:
            self._warned_bypass = True
            log.warning("worker is at max_concurrency; bypass_concurrency jobs may still run (cap: %s)", cap or "unlimited")
        return room

    def _start_reserved(self, envelope: dict) -> None:
        self._run_envelope(envelope)  # replaces the placeholder reservation with the run's real kill event

    def _drain(self, threads: list[threading.Thread]) -> None:
        grace = float(os.getenv("WORKER_SHUTDOWN_GRACE_SECONDS", "25"))
        deadline = time.monotonic() + grace
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            leftover = list(self._active.values())
        for event in leftover:  # grace expired: cancel so each run still reports its end
            event.reason = "shutdown"
            event.set()
        for t in threads:
            t.join(10)
        self.shipper.close()
        self.halt.set()


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = HttpWorker(
        base_url=os.getenv("HYDRA_API_URL", "http://127.0.0.1:8000"),
        token=os.getenv("HYDRA_TOKEN", ""),
        worker_id=os.getenv("WORKER_ID") or f"lite-{socket.gethostname()}-{os.getpid()}",
        max_concurrency=int(os.getenv("MAX_CONCURRENCY", "2")),
        tags=[t.strip() for t in os.getenv("WORKER_TAGS", "").split(",") if t.strip()],
    )

    def _graceful(signum, _frame):
        log.info("signal %s: draining", signum)
        worker.stop.set()

    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)
    worker.run()
    return 0
