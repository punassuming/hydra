"""Trigger loop: turn due schedules into pending runs, honouring misfire and overlap policies."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from scheduler.models.job_definition import ScheduleConfig
from scheduler.utils.schedule import advance_schedule, cron_next

from .store import Store
from .store.store import now_utc

log = logging.getLogger("hydra_lite.scheduling")

# A due tick that is older than this was missed (daemon down/asleep), not merely processed on the next loop pass.
MISFIRE_GRACE_SECONDS = 30
# Safety valve when walking a long outage tick by tick.
MAX_TICKS_WALKED = 10_000


def plan_ticks(schedule: ScheduleConfig, now: datetime) -> tuple[list[datetime], ScheduleConfig]:
    """All ticks due at or before ``now`` (oldest first) and the schedule advanced past them."""
    ticks: list[datetime] = []
    current = schedule
    while current.next_run_at is not None and current.next_run_at <= now and len(ticks) < MAX_TICKS_WALKED:
        ticks.append(current.next_run_at)
        current = advance_schedule(current)
    if current.next_run_at is not None and current.next_run_at <= now:  # outage longer than the walk cap: rebase on now
        if current.mode == "cron" and current.cron:
            current = current.model_copy(update={"next_run_at": cron_next(current, now)})
        else:
            current = current.model_copy(update={"next_run_at": now + timedelta(seconds=current.interval_seconds or 1)})
    return ticks, current


def select_ticks(schedule: ScheduleConfig, ticks: list[datetime], now: datetime) -> tuple[list[datetime], list[datetime]]:
    """Apply ``misfire_policy``: returns (ticks to run, ticks dropped)."""
    if not ticks:
        return [], []
    late = [t for t in ticks if (now - t).total_seconds() > MISFIRE_GRACE_SECONDS]
    on_time = [t for t in ticks if t not in late]
    policy = schedule.misfire_policy
    if policy == "skip":
        return on_time, late
    if policy == "catch_up":
        limit = max(schedule.catch_up_limit, 1)
        return ticks[-limit:], ticks[:-limit]
    # run_once (default): collapse everything due into a single run, labelled with the latest tick
    return ticks[-1:], ticks[:-1]


def tick(store: Store, wake: threading.Event | None = None, now: datetime | None = None) -> int:
    """Enqueue every due job's runs and advance its schedule. Returns runs queued."""
    now = now or now_utc()
    queued = 0
    for job in store.due_jobs(now):
        try:
            schedule = ScheduleConfig.model_validate(job.get("schedule") or {})
            ticks, next_schedule = plan_ticks(schedule, now)
            run_ticks, dropped = select_ticks(schedule, ticks, now)
            if dropped:
                store.add_schedule_event(
                    job["_id"],
                    "misfire_dropped",
                    {
                        "policy": schedule.misfire_policy,
                        "dropped": len(dropped),
                        "first": dropped[0].isoformat(),
                        "last": dropped[-1].isoformat(),
                    },
                )
            for scheduled_ts in run_ticks:
                if schedule.overlap_policy == "skip" and store.open_run_count(job["_id"]) > 0:
                    store.add_schedule_event(job["_id"], "overlap_skipped", {"tick": scheduled_ts.isoformat()})
                    continue
                store.enqueue_run(
                    job["_id"],
                    trigger="schedule",
                    priority=int(job.get("priority", 5)),
                    scheduled_ts=scheduled_ts,
                    exclusive=schedule.overlap_policy == "queue",
                )
                queued += 1
            store.update_job(job["_id"], {"schedule": next_schedule.model_dump(mode="json")}, changed_by="scheduler")
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
