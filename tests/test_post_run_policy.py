"""The post-run decision is shared by the full and lite editions; pin it here."""

from unittest.mock import MagicMock, patch

import pytest

from scheduler.run_events import _handle_run_end
from scheduler.utils.post_run import FINAL_FAILURE, NONE, RETRY, TRIGGER_DEPENDENTS, decide_post_run, sla_exceeded

JOB = {"max_retries": 2, "retry_delay_seconds": 10, "priority": 7}


@pytest.mark.parametrize(
    ("status", "job", "attempt", "action"),
    [
        ("success", JOB, 0, TRIGGER_DEPENDENTS),
        ("success", None, 0, TRIGGER_DEPENDENTS),
        ("failed", JOB, 0, RETRY),
        ("timed_out", JOB, 1, RETRY),
        ("failed", JOB, 2, FINAL_FAILURE),
        ("failed", {"max_retries": 0}, 0, FINAL_FAILURE),
        ("failed", {}, 0, NONE),  # empty doc == unknown job
        ("failed", None, 0, NONE),
        ("running", JOB, 0, NONE),
        ("pending", JOB, 0, NONE),
    ],
)
def test_decide_post_run(status, job, attempt, action):
    assert decide_post_run(status, job, attempt).action == action


def test_retry_decision_carries_attempt_and_backoff():
    d = decide_post_run("failed", JOB, 1, rng=lambda: 0.5)  # jitter factor 1.0 at rng 0.5
    assert d.action == RETRY and d.retry_attempt == 2 and d.delay_seconds == 20  # 10s base doubled for attempt 2


def test_sla_exceeded():
    assert sla_exceeded({"sla_max_duration_seconds": 30}, 31)
    assert not sla_exceeded({"sla_max_duration_seconds": 30}, 30)
    assert not sla_exceeded({"sla_max_duration_seconds": 0}, 999)
    assert not sla_exceeded({"sla_max_duration_seconds": "x"}, 999)
    assert not sla_exceeded(None, 999)


def _end_payload(status, retry_attempt=0):
    return {"type": "run_end", "run_id": "r1", "job_id": "j1", "domain": "prod", "status": status, "retry_attempt": retry_attempt}


@pytest.mark.parametrize("status", ["failed", "timed_out"])
def test_full_edition_handler_follows_the_shared_decision(status):
    db = MagicMock()
    db.job_runs.find_one.return_value = {"status": "running"}
    db.job_runs.update_one.return_value = MagicMock(matched_count=1)
    db.job_definitions.find_one.return_value = {**JOB, "on_failure_webhooks": ["http://x"]}
    with (
        patch("scheduler.run_events.get_db", return_value=db),
        patch("scheduler.run_events._enqueue_job_for_retry") as retry,
        patch("scheduler.run_events._fire_webhooks_async") as hooks,
        patch("scheduler.run_events._fire_email_alert_async"),
        patch("scheduler.run_events.append_worker_op"),
    ):
        _handle_run_end(_end_payload(status, 0))
        assert retry.call_args.kwargs["retry_attempt"] == 1 and not hooks.called
        retry.reset_mock()
        _handle_run_end(_end_payload(status, 2))
        assert not retry.called and hooks.called  # retries exhausted -> final failure webhooks
