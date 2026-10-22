"""In-process worker pool: threads that claim runs from the store and execute them."""

from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Optional

from ..lifecycle import Lifecycle
from ..logs import LogStore
from ..store import NotFound, Store
from .killevent import KillEvent
from .meta import build_worker_meta
from .runner import LocalSink, execute_run

log = logging.getLogger("hydra_lite.worker")


class WorkerPool:
    def __init__(
        self, store: Store, logs: LogStore, lifecycle: Lifecycle, max_concurrency: int = 4, worker_id: Optional[str] = None
    ):
        self.store = store
        self.logs = logs
        self.lifecycle = lifecycle
        self.max_concurrency = max(1, max_concurrency)
        self.worker_id = worker_id or f"local-{socket.gethostname()}"
        self.stop = threading.Event()
        self.wake = lifecycle.wake
        self._kills: dict[str, KillEvent] = {}
        self._active: dict[str, tuple[str, str]] = {}  # run_id -> (job_id, user)
        self._kill_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self.state = "online"  # online | draining | offline
        self.running = 0
        self._count_lock = threading.Lock()

    def start(self) -> None:
        meta = build_worker_meta([])
        self.store.register_worker(
            self.worker_id, os.getpid(), self.max_concurrency, tags=[], capabilities=meta["capabilities"].split(","), meta=meta
        )
        for i in range(self.max_concurrency):
            t = threading.Thread(target=self._loop, name=f"hydra-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        hb = threading.Thread(target=self._heartbeat, name="hydra-worker-hb", daemon=True)
        hb.start()
        self._threads.append(hb)

    def shutdown(self, timeout: float = 10.0) -> None:
        self.stop.set()
        self.wake.set()
        with self._kill_lock:
            for event in self._kills.values():
                event.set()
        for t in self._threads:
            t.join(timeout=timeout)

    def active(self) -> tuple[list[str], list[str]]:
        """(running job ids, running users) for the worker listing."""
        with self._kill_lock:
            pairs = list(self._active.values())
        return [j for j, _ in pairs], sorted({u for _, u in pairs})

    def kill(self, run_id: str, reason: str = "request") -> bool:
        with self._kill_lock:
            event = self._kills.get(run_id)
        if event is None:
            return False
        event.reason = reason
        event.set()
        return True

    def _heartbeat(self) -> None:
        while not self.stop.wait(2.0):
            try:
                self.store.heartbeat(self.worker_id)
            except NotFound:
                self.store.register_worker(self.worker_id, os.getpid(), self.max_concurrency)

    def _loop(self) -> None:
        while not self.stop.is_set():
            if self.state != "online":
                self.stop.wait(0.5)
                continue
            try:
                run = self.store.claim_run(self.worker_id)
            except Exception:
                log.exception("claim failed")
                self.stop.wait(1.0)
                continue
            if run is None:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            kill_event = KillEvent()
            with self._kill_lock:
                self._kills[run["id"]] = kill_event
            with self._count_lock:
                self.running += 1
            try:
                job = self.store.get_job(run["job_id"])
                with self._kill_lock:
                    self._active[run["id"]] = (job["_id"], job.get("user", "default"))
                execute_run(LocalSink(self.store, self.logs, self.lifecycle, self.worker_id), run, job, kill_event)
            except NotFound:
                self.lifecycle.finalize(run["id"], "failed", returncode=1, reason="job was deleted before the run started")
            except Exception:
                log.exception("worker loop error")
            finally:
                with self._count_lock:
                    self.running -= 1
                with self._kill_lock:
                    self._kills.pop(run["id"], None)
                    self._active.pop(run["id"], None)
