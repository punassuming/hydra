"""Trigger loop: turn due schedules into pending runs, honouring misfire and overlap policies."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from scheduler.models.job_definition import ScheduleConfig
from scheduler.utils.schedule import advance_schedule, cron_next

from .store import Store
from .store.store import norm_ts, now_utc

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
