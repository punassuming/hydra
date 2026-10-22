"""Trigger loop: turn due schedules into queued runs."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from croniter import croniter

from scheduler.models.job_definition import ScheduleConfig
from scheduler.utils.schedule import advance_schedule

from .store import Store
from .store.store import now_utc

log = logging.getLogger("hydra_lite.scheduling")


def next_after(schedule: ScheduleConfig, now: datetime) -> ScheduleConfig:
    """Advance ``schedule`` and skip any missed ticks (run-once-on-resume semantics)."""
    advanced = advance_schedule(schedule)
    nxt = advanced.next_run_at
    if nxt is None or nxt > now:
        return advanced
    if advanced.mode == "cron" and advanced.cron:
        nxt = croniter(advanced.cron, now).get_next(datetime)
    else:
        nxt = now + timedelta(seconds=advanced.interval_seconds or 1)
    if advanced.end_at and nxt > advanced.end_at:
        return advanced.model_copy(update={"next_run_at": None, "enabled": False})
    return advanced.model_copy(update={"next_run_at": nxt})


def tick(store: Store, wake: threading.Event | None = None, now: datetime | None = None) -> int:
    """Enqueue every due job once and advance its schedule. Returns runs queued."""
    now = now or now_utc()
    queued = 0
    for job in store.due_jobs(now):
        try:
            schedule = ScheduleConfig.model_validate(job.get("schedule") or {})
            scheduled_for = schedule.next_run_at
            store.enqueue_run(
                job["_id"],
                trigger="schedule",
                priority=int(job.get("priority", 5)),
                scheduled_for=scheduled_for,
            )
            queued += 1
            schedule = next_after(schedule, now)
            store.update_job(job["_id"], {"schedule": schedule.model_dump(mode="json")}, changed_by="scheduler")
        except Exception:  # one bad job must not stall the loop
            log.exception("failed to trigger job %s", job.get("_id"))
    if queued and wake:
        wake.set()
    return queued


def trigger_loop(store: Store, stop: threading.Event, wake: threading.Event, interval: float = 1.0) -> None:
    while not stop.is_set():
        try:
            tick(store, wake)
        except Exception:
            log.exception("trigger loop error")
        stop.wait(interval)


__all__ = ["next_after", "tick", "trigger_loop", "timezone"]
