"""Background maintenance loops: timeout backstop, SLA monitor, retention."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from scheduler.utils.post_run import sla_exceeded

from .lifecycle import Lifecycle
from .store import Store
from .store.store import now_utc

log = logging.getLogger("hydra_lite.loops")

# The executor enforces ``timeout`` itself; the backstop only fires if a run overshoots it by this much.
TIMEOUT_GRACE_SECONDS = 10


def _elapsed(run: dict, now: datetime) -> float | None:
    return (now - datetime.fromisoformat(run["start_ts"])).total_seconds() if run.get("start_ts") else None


def enforce_timeouts(store: Store, router, now: datetime | None = None) -> list[str]:
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
            if router.kill(run["id"], reason="timeout"):
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


UNREPORTED_RUNNING_GRACE_SECONDS = 5
UNREPORTED_DISPATCHED_GRACE_SECONDS = 15


def reconcile_worker(
    store: Store, lifecycle: Lifecycle, worker_id: str, reported: set[str], now: datetime | None = None, grace: bool = True
) -> list[str]:
    """Recover runs the daemon assigns to ``worker_id`` that the worker does not report holding.

    This is what catches a worker that crashed and was restarted under the same id (it heartbeats again, so
    the reaper never sees it go stale). A short grace avoids racing a run that was just claimed or started.
    On (re)registration ``grace`` is off: a freshly started process holds nothing.
    """
    now = now or now_utc()
    recovered = []
    for run in store.worker_runs(worker_id, ("dispatched", "running")):
        if run["id"] in reported:
            continue
        running = run["status"] == "running"
        ref = run["start_ts"] if running else run["dispatched_at"]
        limit = UNREPORTED_RUNNING_GRACE_SECONDS if running else UNREPORTED_DISPATCHED_GRACE_SECONDS
        if grace and ref and (now - datetime.fromisoformat(ref)).total_seconds() < limit:
            continue
        if running:
            lifecycle.finalize(
                run["id"], "failed", reason=f"lost: worker {worker_id} no longer holds this run", event_type="lost"
            )
        elif not store.requeue_run(run["id"], f"worker {worker_id} no longer holds this run"):
            continue
        else:
            lifecycle.wake.set()
        recovered.append(run["id"])
    return recovered


def reap_workers(store: Store, lifecycle: Lifecycle, ttl: float, prune_seconds: float, now: datetime | None = None) -> list[str]:
    """Recover runs owned by workers that stopped heartbeating; forget workers gone for a long time.

    Dispatched-but-unstarted runs go back to pending; running ones are lost (failed + normal retry policy).
    Idempotent: once a worker's runs are handled, later passes find nothing to do.
    """
    now = now or now_utc()
    dead = []
    for worker in store.stale_workers(now - timedelta(seconds=ttl)):
        wid = worker["id"]
        for run in store.worker_runs(wid, ("dispatched",)):
            if store.requeue_run(run["id"], f"worker {wid} stopped heartbeating"):
                lifecycle.wake.set()
        for run in store.worker_runs(wid, ("running",)):
            lifecycle.finalize(run["id"], "failed", reason=f"lost: worker {wid} stopped heartbeating", event_type="lost")
        gone_for = (now - datetime.fromisoformat(worker["last_heartbeat"])).total_seconds()
        if gone_for > prune_seconds and not store.worker_runs(wid):
            store.delete_worker(wid)
        dead.append(wid)
    return dead


def maintenance_loop(store: Store, lifecycle: Lifecycle, router, logs, stop: threading.Event, config) -> None:
    last_purge = 0.0
    import time

    while not stop.is_set():
        try:
            enforce_timeouts(store, router)
            reap_workers(store, lifecycle, config.heartbeat_ttl, config.worker_prune_seconds)
            check_sla(store, lifecycle)
            if time.monotonic() - last_purge >= config.retention_check_seconds:
                last_purge = time.monotonic()
                purged = purge_old_runs(store, logs, config.retention_days)
                if purged:
                    log.info("retention purged %d run(s)", purged)
        except Exception:
            log.exception("maintenance loop error")
        stop.wait(2.0)
