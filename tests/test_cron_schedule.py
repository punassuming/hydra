"""Next-run computation for cron schedules.

croniter decides when every cron job fires, but no other test computes a cron
next_run, so a croniter upgrade that shifts semantics (day-of-week handling,
month rollover, tz-awareness) would silently reschedule jobs. All times are
UTC; 2026-03-15 is a Sunday.
"""

from datetime import datetime, timezone

import pytest
from croniter import croniter
from pydantic import ValidationError

from scheduler.models.job_definition import ScheduleConfig
from scheduler.utils.schedule import advance_schedule, initialize_schedule


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def cron(expr: str, **extra) -> ScheduleConfig:
    return ScheduleConfig(mode="cron", cron=expr, **extra)


NOW = utc(2026, 3, 15, 10, 2, 30)  # a Sunday


@pytest.mark.parametrize(
    "expr, now, expected",
    [
        ("*/5 * * * *", NOW, utc(2026, 3, 15, 10, 5)),
        ("*/2 * * * *", NOW, utc(2026, 3, 15, 10, 4)),
        ("0 9 * * 1-5", NOW, utc(2026, 3, 16, 9, 0)),  # Sunday -> Monday 09:00
        ("0 9 * * 1-5", utc(2026, 3, 13, 17, 0), utc(2026, 3, 16, 9, 0)),  # Friday evening -> Monday
        ("0 0 1 1 *", NOW, utc(2027, 1, 1, 0, 0)),
        ("0 0 * * *", utc(2026, 12, 31, 23, 59, 59), utc(2027, 1, 1, 0, 0)),  # year rollover
        ("30 23 31 * *", utc(2026, 4, 30, 23, 45), utc(2026, 5, 31, 23, 30)),  # 30-day month
        ("30 23 31 * *", utc(2026, 1, 31, 23, 45), utc(2026, 3, 31, 23, 30)),  # February has no 31st
        ("0 0 29 2 *", utc(2026, 1, 1, 0, 0), utc(2028, 2, 29, 0, 0)),  # next leap day
        ("0 12 * * 0", NOW, utc(2026, 3, 15, 12, 0)),  # Sunday == 0
    ],
)
def test_initialize_schedule_computes_the_next_fire_time(expr, now, expected):
    result = initialize_schedule(cron(expr), now).next_run_at
    assert result == expected
    assert result.tzinfo is not None and result.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "expr, last, expected",
    [
        ("*/5 * * * *", utc(2026, 3, 15, 10, 5), utc(2026, 3, 15, 10, 10)),
        ("0 9 * * 1-5", utc(2026, 3, 13, 9, 0), utc(2026, 3, 16, 9, 0)),
        ("0 9 * * 1-5", utc(2026, 3, 16, 9, 0), utc(2026, 3, 17, 9, 0)),
    ],
)
def test_advance_schedule_moves_strictly_past_the_last_run(expr, last, expected):
    schedule = cron(expr, next_run_at=last)
    assert advance_schedule(schedule).next_run_at == expected


def test_a_start_in_the_future_delays_the_first_run():
    schedule = cron("*/5 * * * *", start_at=utc(2026, 4, 1, 0, 0))
    assert initialize_schedule(schedule, NOW).next_run_at == utc(2026, 4, 1, 0, 5)


def test_a_next_run_past_end_at_is_dropped_and_advance_disables_the_schedule():
    schedule = cron("0 0 1 1 *", end_at=utc(2026, 12, 31))
    assert initialize_schedule(schedule, NOW).next_run_at is None

    finishing = cron("*/5 * * * *", end_at=utc(2026, 3, 15, 10, 6), next_run_at=utc(2026, 3, 15, 10, 5))
    advanced = advance_schedule(finishing)
    assert advanced.next_run_at is None and advanced.enabled is False


def test_disabled_and_immediate_schedules_have_no_next_run():
    assert initialize_schedule(cron("*/5 * * * *", enabled=False), NOW).next_run_at is None
    assert initialize_schedule(ScheduleConfig(mode="immediate"), NOW).next_run_at is None


# Every cron form that appears in this repo's examples, templates and tests.
CRON_FORMS_IN_USE = ["*/2 * * * *", "*/5 * * * *", "0 9 * * 1-5", "0 0 1 1 *"]


@pytest.mark.parametrize("expr", CRON_FORMS_IN_USE)
def test_cron_forms_used_in_this_repo_stay_valid(expr):
    assert croniter.is_valid(expr)
    assert cron(expr).cron == expr


@pytest.mark.parametrize("expr", ["", "not a cron", "61 * * * *", "* * *", "* * * * * * * *", "0 0 32 1 *", "0 24 * * *"])
def test_invalid_cron_expressions_are_rejected_at_submit(expr):
    with pytest.raises((ValidationError, ValueError)):
        cron(expr)
