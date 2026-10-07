import logging

import pytest

from scheduler.api import workers as workers_api
from scheduler.models.worker_info import WorkerInfo


@pytest.fixture(autouse=True)
def _clear_warn_cache():
    workers_api._protocol_warned.clear()
    yield
    workers_api._protocol_warned.clear()


def test_matching_version_is_not_a_mismatch(caplog):
    with caplog.at_level(logging.WARNING, logger="scheduler.api.workers"):
        assert workers_api._protocol_mismatch("prod", "w1", workers_api.EXPECTED_WORKER_PROTOCOL_VERSION) is False
    assert caplog.records == []


def test_different_version_is_flagged_and_logged_once(caplog):
    with caplog.at_level(logging.WARNING, logger="scheduler.api.workers"):
        assert workers_api._protocol_mismatch("prod", "w1", "0.9") is True
        assert workers_api._protocol_mismatch("prod", "w1", "0.9") is True
    warnings = [r for r in caplog.records if "protocol version" in r.message]
    assert len(warnings) == 1
    assert "w1" in warnings[0].message and "0.9" in warnings[0].message


def test_worker_that_reports_no_version_is_flagged():
    assert workers_api._protocol_mismatch("prod", "old-worker", None) is True


def test_a_new_version_for_the_same_worker_warns_again(caplog):
    with caplog.at_level(logging.WARNING, logger="scheduler.api.workers"):
        workers_api._protocol_mismatch("prod", "w1", "0.9")
        workers_api._protocol_mismatch("prod", "w1", "0.8")
    assert len([r for r in caplog.records if "protocol version" in r.message]) == 2


def test_warn_cache_stays_bounded():
    for i in range(workers_api._PROTOCOL_WARN_CACHE_MAX + 50):
        workers_api._protocol_mismatch("prod", f"pod-{i}", "0.9")
    assert len(workers_api._protocol_warned) <= workers_api._PROTOCOL_WARN_CACHE_MAX


def test_worker_info_defaults_to_no_mismatch():
    info = WorkerInfo(
        worker_id="w1", os="linux", tags=[], allowed_users=[], max_concurrency=1, current_running=0
    )
    assert info.protocol_mismatch is False
