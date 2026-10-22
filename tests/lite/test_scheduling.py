from datetime import datetime, timedelta, timezone

import pytest

from hydra_lite.jobs import build_job
from hydra_lite.scheduling import next_after, tick
from hydra_lite.store import Store
from scheduler.models.job_definition import ScheduleConfig

UTC = timezone.utc


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "h.db")
    yield s
    s.close()


def _job(name, schedule, now):
    return build_job({"name": name, "executor": {"type": "shell", "script": "echo hi"}, "schedule": schedule}, now=now)


def test_interval_due_job_is_queued_once_and_advanced(store):
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    job = store.create_job(_job("i", {"mode": "interval", "interval_seconds": 60}, now))
    assert tick(store, now=now) == 1
    assert tick(store, now=now) == 0  # next_run_at moved forward
    assert tick(store, now=now + timedelta(seconds=61)) == 1
    runs = store.list_runs(job_id=job["_id"])
    assert len(runs) == 2 and all(r["trigger"] == "schedule" for r in runs)


def test_missed_ticks_collapse_to_one_run(store):
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    job = store.create_job(_job("lag", {"mode": "interval", "interval_seconds": 60}, now))
    later = now + timedelta(hours=5)  # daemon was down
    assert tick(store, now=later) == 1
    assert tick(store, now=later) == 0
    nxt = datetime.fromisoformat(store.get_job(job["_id"])["schedule"]["next_run_at"])
    assert later < nxt <= later + timedelta(seconds=60)


def test_cron_next_after_skips_to_future():
    now = datetime(2026, 3, 10, 12, 7, tzinfo=UTC)
    s = ScheduleConfig(mode="cron", cron="*/5 * * * *", next_run_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC))
    assert next_after(s, now).next_run_at == datetime(2026, 3, 10, 12, 10, tzinfo=UTC)


def test_end_window_disables_schedule():
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    s = ScheduleConfig(mode="interval", interval_seconds=60, next_run_at=now, end_at=now + timedelta(seconds=30))
    out = next_after(s, now)
    assert out.next_run_at is None and out.enabled is False


def test_disabled_job_not_triggered(store):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.create_job(_job("off", {"mode": "interval", "interval_seconds": 60, "enabled": False}, now))
    assert tick(store, now=now + timedelta(hours=1)) == 0
