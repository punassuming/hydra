"""Spawns, restarts, scales and stops worker processes for the daemon."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import Config
from ..store import NotFound, Store
from ..worker.router import WorkerRouter

log = logging.getLogger("hydra_lite.supervisor")

RESTART_BACKOFF_FLOOR, RESTART_BACKOFF_CAP = 1.0, 30.0
STOP_GRACE_SECONDS = 30.0
SCALE_UP_COOLDOWN_SECONDS = 2.0


@dataclass
class ManagedWorker:
    worker_id: str
    tags: list[str]
    max_concurrency: int
    proc: Optional[subprocess.Popen] = None
    wanted: bool = True  # False once an operator asked it to stop
    permanent: bool = False  # part of the default pool (never idle-stopped, restarted when it dies)
    restarts: int = 0
    backoff: float = RESTART_BACKOFF_FLOOR
    next_start: float = 0.0
    last_busy: float = field(default_factory=time.monotonic)
    stop_deadline: Optional[float] = None


class Supervisor:
    def __init__(self, config: Config, store: Store, router: WorkerRouter, base_url: str, token: str):
        self.config, self.store, self.router = config, store, router
        self.base_url, self.token = base_url, token
        self.workers: dict[str, ManagedWorker] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_scale_up = 0.0

    # ----------------------------------------------------------------- control
    def start(self) -> None:
        for _ in range(max(0, self.config.default_workers)):
            self.spawn(permanent=True)
        self._thread = threading.Thread(target=self._loop, name="hydra-supervisor", daemon=True)
        self._thread.start()

    def spawn(
        self, count: int = 1, tags: Optional[list[str]] = None, max_concurrency: Optional[int] = None, permanent: bool = False
    ) -> list[str]:
        ids = []
        with self._lock:
            for _ in range(max(1, count)):
                if len(self._live()) >= self.config.max_workers and not permanent:
                    break
                wid = f"lite-{uuid.uuid4().hex[:8]}"
                worker = ManagedWorker(
                    wid,
                    tags if tags is not None else list(self.config.worker_tags),
                    max_concurrency or self.config.max_concurrency,
                    permanent=permanent,
                )
                self.workers[wid] = worker
                self._launch(worker)
                ids.append(wid)
        return ids

    def stop_worker(self, worker_id: str) -> bool:
        """Drain a worker (finish in-flight runs) and let it exit; terminate if it overstays."""
        with self._lock:
            worker = self.workers.get(worker_id)
            if worker is None:
                return False
            worker.wanted = False
            worker.permanent = False
            worker.stop_deadline = time.monotonic() + STOP_GRACE_SECONDS + 10
        try:
            self.store.set_worker_state(worker_id, "draining")
        except NotFound:
            pass
        self.router.request_stop(worker_id)
        return True

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            procs = [(w, w.proc) for w in self.workers.values() if w.proc and w.proc.poll() is None]
            for w, _ in procs:
                w.wanted = False
        for _, proc in procs:
            self._terminate(proc, force=False)
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        for _, proc in procs:
            try:
                proc.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                self._terminate(proc, force=True)
        if self._thread:
            self._thread.join(timeout=5)

    # ---------------------------------------------------------------- internals
    def _live(self) -> list[ManagedWorker]:
        return [w for w in self.workers.values() if w.wanted]

    def _launch(self, worker: ManagedWorker) -> None:
        log_dir = Path(self.config.data_dir) / "workers"
        log_dir.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "HYDRA_API_URL": self.base_url,
            "HYDRA_TOKEN": self.token,
            "WORKER_ID": worker.worker_id,
            "MAX_CONCURRENCY": str(worker.max_concurrency),
            "WORKER_TAGS": ",".join(worker.tags),
            "WORKER_SHUTDOWN_GRACE_SECONDS": str(int(STOP_GRACE_SECONDS)),
        }
        kwargs: dict = {"stdin": subprocess.DEVNULL, "env": env}
        out = open(log_dir / f"{worker.worker_id}.log", "ab")  # noqa: SIM115 - owned by the child
        kwargs.update(stdout=out, stderr=subprocess.STDOUT)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        worker.proc = subprocess.Popen([sys.executable, "-m", "hydra_lite.worker"], **kwargs)  # noqa: S603
        out.close()
        worker.last_busy = time.monotonic()
        log.info("started worker %s (pid %s)", worker.worker_id, worker.proc.pid)

    @staticmethod
    def _terminate(proc: subprocess.Popen, force: bool) -> None:
        try:
            if sys.platform == "win32":
                if force:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)  # noqa: S603,S607
                else:
                    proc.terminate()
            else:
                proc.kill() if force else proc.terminate()
        except (ProcessLookupError, OSError):
            pass

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self._tick()
            except Exception:
                log.exception("supervisor tick failed")

    def _tick(self) -> None:
        now = time.monotonic()
        with self._lock:
            for worker in list(self.workers.values()):
                proc = worker.proc
                alive = proc is not None and proc.poll() is None
                if not alive:
                    self._handle_exit(worker, now)
                elif worker.stop_deadline and now > worker.stop_deadline:
                    log.warning("worker %s did not drain in time; terminating", worker.worker_id)
                    self._terminate(proc, force=True)
            self._autoscale(now)

    def _handle_exit(self, worker: ManagedWorker, now: float) -> None:
        if worker.proc is not None:
            code = worker.proc.returncode
            worker.proc = None
            if worker.wanted:
                worker.restarts += 1
                worker.next_start = now + worker.backoff
                worker.backoff = min(worker.backoff * 2, RESTART_BACKOFF_CAP)
                log.warning("worker %s exited (%s); restarting in %.0fs", worker.worker_id, code, worker.next_start - now)
            else:
                self.workers.pop(worker.worker_id, None)
                self.router.forget_worker(worker.worker_id)
                return
        if worker.wanted and now >= worker.next_start:
            self._launch(worker)

    def _autoscale(self, now: float) -> None:
        pending = self.store.count_runs("pending")
        running = self.store.count_runs("running") + self.store.count_runs("dispatched")
        online = [w for w in self.workers.values() if w.wanted and w.proc is not None]
        capacity = sum(w.max_concurrency for w in online)
        free = capacity - running
        if (
            pending > max(free, 0)
            and len(self._live()) < self.config.max_workers
            and now - self._last_scale_up >= SCALE_UP_COOLDOWN_SECONDS
        ):
            self._last_scale_up = now
            self.spawn(1)
            return
        idle_after = self.config.idle_stop_seconds
        for worker in online:
            busy = bool(self.store.worker_runs(worker.worker_id)) or pending > 0
            if busy:
                worker.last_busy = now
            elif idle_after > 0 and not worker.permanent and now - worker.last_busy > idle_after:
                log.info("stopping idle worker %s", worker.worker_id)
                self.stop_worker(worker.worker_id)
