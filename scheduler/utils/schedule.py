from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from ..models.job_definition import ScheduleConfig


def cron_next(schedule: ScheduleConfig, after: datetime) -> datetime:
    """Next cron fire time strictly after ``after``, evaluated in ``schedule.timezone``.

    Returns an aware UTC datetime. Both editions use this so a job fires at the same wall-clock time
    everywhere; DST gaps/repeats follow croniter's semantics (pinned in tests/test_cron_schedule.py).
    """
    zone = ZoneInfo(schedule.timezone or "UTC")
    prev_local = after.astimezone(zone)
    local = croniter(schedule.cron, prev_local).get_next(datetime)
    # Fall-back repeats a wall-clock hour; croniter would fire in both occurrences. Skip the second
    # occurrence of the tick we just fired so a job runs once per local wall-clock time.
    if local.replace(tzinfo=None) == prev_local.replace(tzinfo=None) and local.utcoffset() != prev_local.utcoffset():
        local = croniter(schedule.cron, local).get_next(datetime)
    return local.astimezone(timezone.utc)


def _clamp_to_window(candidate: Optional[datetime], schedule: ScheduleConfig) -> Optional[datetime]:
    if not candidate:
        return None
    if schedule.end_at and candidate > schedule.end_at:
        return None
    return candidate


def initialize_schedule(schedule: ScheduleConfig, now: datetime) -> ScheduleConfig:
    """Ensure schedule.next_run_at is set for cron/interval modes."""
    if not schedule.enabled or schedule.mode == "immediate":
        return schedule.model_copy(update={"next_run_at": None})

    if schedule.mode == "cron":
        base = schedule.start_at or now
        base = max(base, now)
        if not schedule.cron:
            raise ValueError("cron schedule requires cron expression")
        next_run = cron_next(schedule, base)
    else:  # interval
        if not schedule.interval_seconds or schedule.interval_seconds <= 0:
            raise ValueError("interval schedule requires positive interval_seconds")
        start = schedule.start_at or now
        next_run = start if start > now else now

    next_run = _clamp_to_window(next_run, schedule)
    return schedule.model_copy(update={"next_run_at": next_run})


def advance_schedule(schedule: ScheduleConfig) -> ScheduleConfig:
    """Advance schedule.next_run_at after a run dispatch."""
    if not schedule.enabled or schedule.mode == "immediate":
        return schedule.model_copy(update={"next_run_at": None})

    last_run = schedule.next_run_at or datetime.now(timezone.utc)

    if schedule.mode == "cron":
        if not schedule.cron:
            raise ValueError("cron schedule requires cron expression")
        next_run = cron_next(schedule, last_run)
    else:
        if not schedule.interval_seconds or schedule.interval_seconds <= 0:
            raise ValueError("interval schedule requires positive interval_seconds")
        next_run = last_run + timedelta(seconds=schedule.interval_seconds)

    next_run = _clamp_to_window(next_run, schedule)
    if next_run is None:
        return schedule.model_copy(update={"next_run_at": None, "enabled": False})
    return schedule.model_copy(update={"next_run_at": next_run})
