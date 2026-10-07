import threading
import time
from unittest.mock import MagicMock, patch

from scheduler.scheduler import timeout_enforcement_loop


def _run_one_pass(running_hash, job_timeout):
    """Run a single iteration of timeout_enforcement_loop against fakes and
    return the redis mock so callers can inspect published kills."""
    r = MagicMock()
    r.smembers.return_value = {"prod"}
    r.scan_iter.return_value = ["job_running:prod:job-1"]
    r.hgetall.return_value = running_hash
    db = MagicMock()
    db.job_definitions.find_one.return_value = {"timeout": job_timeout}

    stop = threading.Event()

    def fake_sleep(_seconds):
        stop.set()

    with patch("scheduler.scheduler.get_redis", return_value=r), \
         patch("scheduler.scheduler.get_db", return_value=db), \
         patch("scheduler.scheduler.time.sleep", side_effect=fake_sleep):
        timeout_enforcement_loop(stop)
    return r


def test_kills_run_using_immutable_started_ts_even_though_heartbeat_is_fresh():
    """Workers overwrite `heartbeat` every ~2s, so elapsed must come from
    started_ts or the timeout backstop can never fire."""
    now = time.time()
    r = _run_one_pass(
        {"run_id": "run-1", "started_ts": str(now - 600), "heartbeat": str(now - 1)},
        job_timeout=60,
    )
    r.publish.assert_called_once_with("job_kill:prod", "run-1")


def test_does_not_kill_a_run_within_its_timeout():
    now = time.time()
    r = _run_one_pass(
        {"run_id": "run-1", "started_ts": str(now - 10), "heartbeat": str(now - 1)},
        job_timeout=60,
    )
    r.publish.assert_not_called()


def test_older_workers_without_started_ts_fall_back_to_heartbeat():
    now = time.time()
    # Fresh heartbeat and no started_ts: treated as just started (the old, weaker behaviour).
    r = _run_one_pass({"run_id": "run-1", "heartbeat": str(now - 1)}, job_timeout=60)
    r.publish.assert_not_called()
