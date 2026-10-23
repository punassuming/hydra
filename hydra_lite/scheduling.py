"""Trigger loop: turn due schedules into pending runs, honouring misfire and overlap policies."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from scheduler.models.job_definition import ScheduleConfig
from scheduler.utils.schedule import MAX_TICKS_WALKED, MISFIRE_GRACE_SECONDS, plan_ticks, select_ticks  # shared planner

from .store import Store
from .store.store import norm_ts, now_utc

log = logging.getLogger("hydra_lite.scheduling")

__all__ = ["MAX_TICKS_WALKED", "MISFIRE_GRACE_SECONDS", "plan_ticks", "select_ticks", "tick", "trigger_loop"]


def tick(store: Store, wake: threading.Event | None = None, now: datetime | None = None) -> int:
    """Enqueue every due job's runs and advance its schedule. Returns runs queued.

    Each job is handled in one store transaction (``trigger_schedule``) that compare-and-sets ``next_run_at``,
    so concurrent edits (disable, reschedule) are never overwritten by a stale plan.
    """
    now = now or now_utc()
    queued = 0
    for job in store.due_jobs(now):
        try:
            schedule = ScheduleConfig.model_validate(job.get("schedule") or {})
            ticks, next_schedule = plan_ticks(schedule, now)
            run_ticks, dropped = select_ticks(schedule, ticks, now)
            dropped_detail = (
                {
                    "policy": schedule.misfire_policy,
                    "dropped": len(dropped),
                    "first": dropped[0].isoformat(),
                    "last": dropped[-1].isoformat(),
                }
                if dropped
                else None
            )
            created = store.trigger_schedule(
                job["_id"],
                norm_ts(schedule.next_run_at),
                next_schedule.model_dump(mode="json"),
                [
                    {"scheduled_ts": t, "priority": int(job.get("priority", 5)), "exclusive": schedule.overlap_policy == "queue"}
                    for t in run_ticks
                ],
                dropped=dropped_detail,
                skip_if_open=schedule.overlap_policy == "skip",
            )
            queued += len(created or [])
        except Exception:  # one bad job must not stall the loop
            log.exception("failed to trigger job %s", job.get("_id"))
    if queued and wake:
        wake.set()
    return queued


def trigger_loop(store: Store, stop: threading.Event, wake: threading.Event, interval: float = 1.0) -> None:
    """Fire due schedules; sleep until the next one is due (at most ``interval``) so ticks are not up to a second late."""
    while not stop.is_set():
        try:
            tick(store, wake)
            until = store.seconds_until_next_due()
        except Exception:
            log.exception("trigger loop error")
            until = None
        stop.wait(interval if until is None else min(interval, max(0.005, until)))
