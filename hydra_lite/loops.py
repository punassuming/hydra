"""Background maintenance loops: timeout backstop, SLA monitor, retention."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from scheduler.utils.post_run import sla_exceeded

from .lifecycle import Lifecycle
from .store import Store
from .store.store import now_utc
from .worker.inproc import WorkerPool

log = logging.getLogger("hydra_lite.loops")

# The executor enforces ``timeout`` itself; the backstop only fires if a run overshoots it by this much.
TIMEOUT_GRACE_SECONDS = 10


def _elapsed(run: dict, now: datetime) -> float | None:
    return (now - datetime.fromisoformat(run["start_ts"])).total_seconds() if run.get("start_ts") else None


def enforce_timeouts(store: Store, pool: WorkerPool, now: datetime | None = None) -> list[str]:
    now = now or now_utc()
    killed = []
    for run in store.running_runs():
        elapsed = _elapsed(run, now)
        try:
            job = store.get_job(run["job_id"])
        except LookupError:
            continue
        timeout = int(job.get("timeout") or 0)
        if elapsed is not None and timeout > 0 and elapsed > timeout + TIMEOUT_GRACE_SECONDS:
            log.warning("run %s exceeded timeout %ss (%.0fs); killing", run["id"], timeout, elapsed)
            if pool.kill(run["id"], reason="timeout"):
                killed.append(run["id"])
    return killed


def check_sla(store: Store, lifecycle: Lifecycle, now: datetime | None = None) -> list[str]:
    now = now or now_utc()
    alerted = []
    for run in store.running_runs():
        if run["sla_miss_alerted"]:
            continue
        elapsed = _elapsed(run, now)
        try:
            job = store.get_job(run["job_id"])
        except LookupError:
            continue
        if elapsed is not None and sla_exceeded(job, elapsed) and store.mark_sla_alerted(run["id"]):
            sla = int(job["sla_max_duration_seconds"])
            store.add_event(run["id"], "sla_miss", {"sla_seconds": sla, "elapsed": round(elapsed, 1)})
            lifecycle.alert(
                job, run, f"SLA Warning: Job exceeded expected duration of {sla} seconds (running for {elapsed:.1f}s)"
            )
            alerted.append(run["id"])
    return alerted


def purge_old_runs(store: Store, logs, days: int, now: datetime | None = None) -> int:
    """Delete runs, events and log files older than ``days`` (0 disables)."""
    if days <= 0:
        return 0
    ids = store.purge_runs_before((now or now_utc()) - timedelta(days=days))
    for run_id in ids:
        logs.delete(run_id)
    return len(ids)


def maintenance_loop(
    store: Store, lifecycle: Lifecycle, pool: WorkerPool, logs, stop: threading.Event, retention_days: int, retention_every: float
) -> None:
    last_purge = 0.0
    import time

    while not stop.is_set():
        try:
            enforce_timeouts(store, pool)
            check_sla(store, lifecycle)
            if time.monotonic() - last_purge >= retention_every:
                last_purge = time.monotonic()
                purged = purge_old_runs(store, logs, retention_days)
                if purged:
                    log.info("retention purged %d run(s)", purged)
        except Exception:
            log.exception("maintenance loop error")
        stop.wait(5.0)
