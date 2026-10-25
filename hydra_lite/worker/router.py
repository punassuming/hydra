"""Routes control requests (kill, graceful stop) to whichever worker owns a run."""

from __future__ import annotations

import threading
from typing import Optional

from ..store import NotFound, Store
from ..store.store import TERMINAL_STATUSES


class WorkerRouter:
    def __init__(self, store: Store, pool=None):
        self.store = store
        self.pool = pool  # in-process pool, if running
        self._kills: dict[str, str] = {}  # run_id -> reason, delivered via the owning worker's heartbeat
        self._stops: set[str] = set()  # worker ids asked to exit once drained
        self._lock = threading.Lock()

    def kill(self, run_id: str, reason: str = "request") -> bool:
        if self.pool is not None and self.pool.kill(run_id, reason):
            return True
        try:
            run = self.store.get_run(run_id)
        except NotFound:
            return False
        if run["status"] in ("dispatched", "running") and run.get("worker_id"):
            with self._lock:
                self._kills[run_id] = reason
            return True
        return False

    def kills_for(self, running_run_ids: list[str]) -> list[dict]:
        """Kill orders for the runs a worker reports as running; finished orders are dropped."""
        with self._lock:
            pending = dict(self._kills)
        out = []
        for run_id, reason in pending.items():
            try:
                done = self.store.get_run(run_id)["status"] in TERMINAL_STATUSES
            except NotFound:
                done = True
            if done:
                with self._lock:
                    self._kills.pop(run_id, None)
            elif run_id in running_run_ids:
                out.append({"run_id": run_id, "reason": reason})
        return out

    def request_stop(self, worker_id: str) -> None:
        with self._lock:
            self._stops.add(worker_id)

    def stop_requested(self, worker_id: str) -> bool:
        with self._lock:
            return worker_id in self._stops

    def forget_worker(self, worker_id: str) -> None:
        with self._lock:
            self._stops.discard(worker_id)


def split_csv(value: object) -> list[str]:
    """Registration metadata uses comma-joined strings (as the full edition's worker hash does); accept lists too."""
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in (value or [])]


def worker_view(worker: dict) -> dict:
    """The worker dict shape ``scheduler.utils.affinity.passes_affinity`` expects."""
    meta = worker.get("meta") or {}
    return {
        "os": meta.get("os", ""),
        "tags": worker.get("tags", []),
        "allowed_users": split_csv(meta.get("allowed_users")),
        "hostname": meta.get("hostname", ""),
        "subnet": meta.get("subnet", ""),
        "deployment_type": meta.get("deployment_type", ""),
        "capabilities": worker.get("capabilities", []),
        "max_concurrency": worker.get("max_concurrency", 1),
    }


__all__ = ["WorkerRouter", "split_csv", "worker_view", "Optional"]
