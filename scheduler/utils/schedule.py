from datetime import datetime, timedelta
from typing import Optional

from croniter import croniter

from ..models.job_definition import ScheduleConfig


def _clamp_to_window(candidate: Optional[datetime], schedule: ScheduleConfig) -> Optional[datetime]:
    if not candidate:
        return None
    if schedule.end_at and candidate > schedule.end_at:
        return None
    return candidate


def initialize_schedule(schedule: ScheduleConfig, now: datetime) -> ScheduleConfig:
    """Ensure schedule.next_run_at is set for cron/interval modes."""
    if not schedule.enabled or schedule.mode == "immediate":
        return schedule.copy(update={"next_run_at": None})

    if schedule.mode == "cron":
        base = schedule.start_at or now
        base = max(base, now)
        if not schedule.cron:
            raise ValueError("cron schedule requires cron expression")
        next_run = croniter(schedule.cron, base).get_next(datetime)
    else:  # interval
        if not schedule.interval_seconds or schedule.interval_seconds <= 0:
            raise ValueError("interval schedule requires positive interval_seconds")
        start = schedule.start_at or now
        next_run = start if start > now else now

    next_run = _clamp_to_window(next_run, schedule)
    return schedule.copy(update={"next_run_at": next_run})


def advance_schedule(schedule: ScheduleConfig) -> ScheduleConfig:
    """Advance schedule.next_run_at after a run dispatch."""
    if not schedule.enabled or schedule.mode == "immediate":
        return schedule.copy(update={"next_run_at": None})

    last_run = schedule.next_run_at or datetime.utcnow()

    if schedule.mode == "cron":
        if not schedule.cron:
            raise ValueError("cron schedule requires cron expression")
        next_run = croniter(schedule.cron, last_run).get_next(datetime)
    else:
        if not schedule.interval_seconds or schedule.interval_seconds <= 0:
            raise ValueError("interval schedule requires positive interval_seconds")
        next_run = last_run + timedelta(seconds=schedule.interval_seconds)

    next_run = _clamp_to_window(next_run, schedule)
    if next_run is None:
        return schedule.copy(update={"next_run_at": None, "enabled": False})
    return schedule.copy(update={"next_run_at": next_run})
