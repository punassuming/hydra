"""Tests for the job_runs retention loop.

job_runs accumulate forever by default; run_retention_loop purges runs
older than HYDRA_RUN_RETENTION_DAYS once an operator opts in — see
scheduler/scheduler.py::run_retention_loop.
"""

import threading
from unittest.mock import MagicMock, patch

from scheduler.scheduler import _purge_old_runs, run_retention_loop


def test_purge_old_runs_disabled_by_default_is_a_noop():
    db = MagicMock()
    deleted = _purge_old_runs(db, retention_days=0)
    assert deleted == 0
    db.job_runs.delete_many.assert_not_called()


def test_purge_old_runs_negative_retention_is_a_noop():
    db = MagicMock()
    deleted = _purge_old_runs(db, retention_days=-5)
    assert deleted == 0
    db.job_runs.delete_many.assert_not_called()


def test_purge_old_runs_deletes_by_start_ts_cutoff():
    db = MagicMock()
    db.job_runs.delete_many.return_value = MagicMock(deleted_count=42)

    deleted = _purge_old_runs(db, retention_days=90)

    assert deleted == 42
    db.job_runs.delete_many.assert_called_once()
    (query,), _kwargs = db.job_runs.delete_many.call_args
    assert set(query.keys()) == {"start_ts"}
    assert set(query["start_ts"].keys()) == {"$lt"}


def test_loop_purges_once_per_wait_interval_then_stops():
    stop_event = threading.Event()
    calls = []

    def _fake_wait(_timeout):
        calls.append("wait")
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._purge_old_runs", return_value=0) as mock_purge:
        run_retention_loop(stop_event)

    mock_purge.assert_called_once()
    assert calls == ["wait"]


def test_loop_survives_purge_exception():
    stop_event = threading.Event()

    def _fake_wait(_timeout):
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._purge_old_runs", side_effect=RuntimeError("boom")):
        # Must not raise — the loop logs and keeps going.
        run_retention_loop(stop_event)
