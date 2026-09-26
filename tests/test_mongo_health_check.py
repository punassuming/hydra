"""Tests for the MongoDB self-healing loop.

pymongo already reconnects transparently on transient errors, but a
persistent failure (e.g. a replica-set failover the driver's own pooling
didn't pick up) previously had no self-healing at the scheduler level. This
loop pings Mongo periodically and resets the client singleton on failure so
the next call rebuilds a fresh connection — see
scheduler/scheduler.py::mongo_health_check_loop.
"""

import threading
from unittest.mock import MagicMock, patch

from scheduler.scheduler import _check_mongo_health, mongo_health_check_loop


def test_check_mongo_health_pings_and_succeeds():
    db = MagicMock()
    _check_mongo_health(db)
    db.command.assert_called_once_with("ping")


def test_check_mongo_health_raises_on_failure():
    db = MagicMock()
    db.command.side_effect = ConnectionError("mongo unreachable")
    try:
        _check_mongo_health(db)
        assert False, "expected _check_mongo_health to raise"
    except ConnectionError:
        pass


def test_loop_checks_once_per_wait_interval_then_stops():
    stop_event = threading.Event()
    calls = []

    def _fake_wait(_timeout):
        calls.append("wait")
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._check_mongo_health") as mock_check, \
         patch("scheduler.scheduler._reset_mongo_client") as mock_reset:
        mongo_health_check_loop(stop_event)

    mock_check.assert_called_once()
    mock_reset.assert_not_called()
    assert calls == ["wait"]


def test_loop_resets_client_and_survives_exception_on_failure():
    stop_event = threading.Event()

    def _fake_wait(_timeout):
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._check_mongo_health", side_effect=RuntimeError("boom")), \
         patch("scheduler.scheduler._reset_mongo_client") as mock_reset:
        # Must not raise — the loop logs, resets the client, and keeps going.
        mongo_health_check_loop(stop_event)

    mock_reset.assert_called_once()


def test_reset_mongo_client_clears_the_singleton():
    from scheduler import mongo_client as mongo_client_module
    from scheduler.scheduler import _reset_mongo_client

    mongo_client_module._mongo_client = MagicMock()
    _reset_mongo_client()
    assert mongo_client_module._mongo_client is None
