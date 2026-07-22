"""Tests for run-event ingestion hardening.

Covers idempotency, anomalous ordering, and crash-recovery semantics for
scheduler/run_events.py.  All tests use in-memory mocks to avoid requiring
live Redis or MongoDB connections.
"""

import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from scheduler.models.job_run import TERMINAL_STATES
from scheduler.run_events import (
    _handle_event,
    _handle_run_end,
    _handle_run_start,
    _recover_staging_events,
    run_event_loop,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_start_payload(run_id="r1", job_id="j1", domain="prod", attempt=1):
    return {
        "type": "run_start",
        "run_id": run_id,
        "job_id": job_id,
        "domain": domain,
        "worker_id": "w1",
        "start_ts": datetime.now(timezone.utc).timestamp(),
        "scheduled_ts": datetime.now(timezone.utc).timestamp(),
        "attempt": attempt,
    }


def _run_end_payload(run_id="r1", job_id="j1", domain="prod", status="success"):
    return {
        "type": "run_end",
        "run_id": run_id,
        "job_id": job_id,
        "domain": domain,
        "worker_id": "w1",
        "end_ts": datetime.now(timezone.utc).timestamp(),
        "status": status,
        "returncode": 0 if status == "success" else 1,
    }


def _make_db(existing_doc=None):
    """Return a minimal mock MongoDB database."""
    db = MagicMock()
    db.job_runs.find_one.return_value = existing_doc
    db.job_runs.update_one.return_value = SimpleNamespace(matched_count=1, upserted_id=None)
    db.job_runs.insert_one.return_value = SimpleNamespace(inserted_id="r1")
    db.job_definitions.find_one.return_value = None
    return db


# ---------------------------------------------------------------------------
# run_start idempotency
# ---------------------------------------------------------------------------

class TestHandleRunStartIdempotency:
    """run_start events must be safe to deliver more than once."""

    def test_first_run_start_inserts_document(self):
        db = _make_db(existing_doc=None)
        upsert_result = SimpleNamespace(matched_count=0, upserted_id="r1")
        db.job_runs.update_one.return_value = upsert_result
        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op"):
            _handle_run_start(_run_start_payload())
        db.job_runs.update_one.assert_called_once()
        _, kwargs = db.job_runs.update_one.call_args
        assert kwargs.get("upsert") is True
        # $setOnInsert must be the only operator used (not $set)
        args = db.job_runs.update_one.call_args[0]
        update_op = args[1]
        assert "$setOnInsert" in update_op
        assert "$set" not in update_op

    def test_duplicate_run_start_is_noop(self):
        """A second run_start for the same run_id must not overwrite the document."""
        # matched_count > 0 means the document already existed
        existing = {"_id": "r1", "status": "running"}
        db = _make_db(existing_doc=existing)
        already_exists = SimpleNamespace(matched_count=1, upserted_id=None)
        db.job_runs.update_one.return_value = already_exists
        db.job_runs.find_one.return_value = existing

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op") as mock_op:
            _handle_run_start(_run_start_payload())

        # append_worker_op must NOT be called — the duplicate is silently dropped
        mock_op.assert_not_called()

    def test_duplicate_run_start_after_terminal_run_end(self):
        """A replayed run_start after run_end has marked the run terminal must be ignored."""
        existing = {"_id": "r1", "status": "success"}
        db = _make_db(existing_doc=existing)
        already_exists = SimpleNamespace(matched_count=1, upserted_id=None)
        db.job_runs.update_one.return_value = already_exists
        db.job_runs.find_one.return_value = existing

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op") as mock_op:
            _handle_run_start(_run_start_payload())

        mock_op.assert_not_called()

    def test_run_start_missing_run_id_is_silently_dropped(self):
        db = _make_db()
        with patch("scheduler.run_events.get_db", return_value=db):
            _handle_run_start({"type": "run_start", "job_id": "j1"})
        db.job_runs.update_one.assert_not_called()

    def test_run_start_missing_job_id_is_silently_dropped(self):
        db = _make_db()
        with patch("scheduler.run_events.get_db", return_value=db):
            _handle_run_start({"type": "run_start", "run_id": "r1"})
        db.job_runs.update_one.assert_not_called()


# ---------------------------------------------------------------------------
# run_end idempotency
# ---------------------------------------------------------------------------

class TestHandleRunEndIdempotency:
    """run_end events must be safe to deliver more than once and must not
    re-trigger post-run actions (retries, webhooks) on replay."""

    def test_normal_run_end_updates_document(self):
        existing = {"_id": "r1", "status": "running", "start_ts": datetime.now(timezone.utc)}
        db = _make_db(existing_doc=existing)
        db.job_runs.update_one.return_value = SimpleNamespace(matched_count=1, upserted_id=None)

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op"), \
             patch("scheduler.run_events._trigger_dependents"):
            _handle_run_end(_run_end_payload(status="success"))

        db.job_runs.update_one.assert_called_once()
        update_filter = db.job_runs.update_one.call_args[0][0]
        # Must guard against updating a run already in a terminal state
        assert "$nin" in update_filter.get("status", {})

    def test_duplicate_run_end_for_terminal_run_is_ignored(self):
        """A replayed run_end for a run already in a terminal state must not
        re-trigger post-run actions."""
        existing = {"_id": "r1", "status": "success", "start_ts": datetime.now(timezone.utc)}
        db = _make_db(existing_doc=existing)

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op") as mock_op, \
             patch("scheduler.run_events._trigger_dependents") as mock_trigger:
            _handle_run_end(_run_end_payload(status="success"))

        # Neither side-effect should fire on a duplicate
        mock_op.assert_not_called()
        mock_trigger.assert_not_called()
        db.job_runs.update_one.assert_not_called()

    def test_duplicate_run_end_for_failed_run_does_not_retry(self):
        """A replayed failed run_end must not enqueue another retry."""
        existing = {"_id": "r1", "status": "failed", "start_ts": datetime.now(timezone.utc)}
        db = _make_db(existing_doc=existing)

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op") as mock_op, \
             patch("scheduler.run_events._enqueue_job_for_retry") as mock_retry:
            _handle_run_end(_run_end_payload(status="failed"))

        mock_retry.assert_not_called()
        mock_op.assert_not_called()

    def test_run_end_missing_run_id_is_silently_dropped(self):
        db = _make_db()
        with patch("scheduler.run_events.get_db", return_value=db):
            _handle_run_end({"type": "run_end", "status": "success"})
        db.job_runs.find_one.assert_not_called()


# ---------------------------------------------------------------------------
# Out-of-order delivery
# ---------------------------------------------------------------------------

class TestRunEndBeforeRunStart:
    """run_end arriving before a persisted run_start must create a fallback
    document and still fire post-run actions exactly once."""

    def test_fallback_doc_created_when_run_start_missing(self):
        db = _make_db(existing_doc=None)  # No existing document
        db.job_runs.update_one.return_value = SimpleNamespace(matched_count=0, upserted_id=None)

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op"), \
             patch("scheduler.run_events._trigger_dependents"):
            _handle_run_end(_run_end_payload(status="success"))

        # insert_one must be called to create the fallback document
        db.job_runs.insert_one.assert_called_once()
        inserted = db.job_runs.insert_one.call_args[0][0]
        assert inserted["_id"] == "r1"
        assert inserted["status"] == "success"

    def test_post_run_actions_fire_for_out_of_order_success(self):
        db = _make_db(existing_doc=None)
        db.job_runs.update_one.return_value = SimpleNamespace(matched_count=0, upserted_id=None)

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op"), \
             patch("scheduler.run_events._trigger_dependents") as mock_trigger:
            _handle_run_end(_run_end_payload(status="success"))

        mock_trigger.assert_called_once()

    def test_concurrent_insert_on_fallback_is_handled_gracefully(self):
        """If insert_one raises DuplicateKeyError (concurrent run_start), the
        handler must not raise and must skip post-run actions."""
        from pymongo.errors import DuplicateKeyError

        existing = {"_id": "r1", "status": "success"}
        db = _make_db(existing_doc=None)
        db.job_runs.insert_one.side_effect = DuplicateKeyError("dup")
        # After the race, the concurrent run_start made the doc terminal
        db.job_runs.find_one.side_effect = [None, existing]

        with patch("scheduler.run_events.get_db", return_value=db), \
             patch("scheduler.run_events.append_worker_op") as mock_op, \
             patch("scheduler.run_events._trigger_dependents") as mock_trigger:
            # Must not raise
            _handle_run_end(_run_end_payload(status="success"))

        mock_trigger.assert_not_called()
        mock_op.assert_not_called()


# ---------------------------------------------------------------------------
# TERMINAL_STATES constant
# ---------------------------------------------------------------------------

class TestTerminalStates:
    def test_terminal_states_contains_expected_values(self):
        assert "success" in TERMINAL_STATES
        assert "failed" in TERMINAL_STATES
        assert "timed_out" in TERMINAL_STATES

    def test_running_not_in_terminal_states(self):
        assert "running" not in TERMINAL_STATES
        assert "pending" not in TERMINAL_STATES
        assert "dispatched" not in TERMINAL_STATES


# ---------------------------------------------------------------------------
# Staging-queue crash recovery
# ---------------------------------------------------------------------------

class TestRecoverStagingEvents:
    """_recover_staging_events() must move events from processing queues back
    to their source queues so they are reprocessed after a restart."""

    def test_no_staging_queues_returns_zero(self):
        r = MagicMock()
        r.scan_iter.return_value = []
        count = _recover_staging_events(r)
        assert count == 0

    def test_single_staged_event_is_moved_back(self):
        r = MagicMock()
        r.scan_iter.return_value = ["run_events:prod:processing"]
        # First call returns the staged event; second call returns None (empty)
        r.rpoplpush.side_effect = [b'{"type":"run_start"}', None]
        count = _recover_staging_events(r)
        assert count == 1
        # Must push back to the source queue (without :processing)
        r.rpoplpush.assert_any_call(
            "run_events:prod:processing", "run_events:prod"
        )

    def test_multiple_staged_events_are_all_recovered(self):
        r = MagicMock()
        r.scan_iter.return_value = ["run_events:prod:processing"]
        # Three events in the staging queue, then empty
        r.rpoplpush.side_effect = [
            b'{"type":"run_start","run_id":"r1"}',
            b'{"type":"run_end","run_id":"r2"}',
            b'{"type":"run_start","run_id":"r3"}',
            None,
        ]
        count = _recover_staging_events(r)
        assert count == 3


# ---------------------------------------------------------------------------
# run_event_loop integration (lightweight)
# ---------------------------------------------------------------------------

class TestRunEventLoop:
    """Verify the event loop processes one event per tick and removes it from
    the staging queue on completion."""

    def test_loop_processes_event_and_clears_staging(self):
        raw = json.dumps({"type": "run_start", "run_id": "r1", "job_id": "j1"}).encode()
        r = MagicMock()
        r.smembers.return_value = ["prod"]
        # First tick: rpoplpush returns an event; second tick: no events → stops
        r.rpoplpush.side_effect = [raw, None]

        stop = threading.Event()

        processed = []

        def fake_handle(payload):
            processed.append(payload)
            stop.set()

        with patch("scheduler.run_events.get_redis", return_value=r), \
             patch("scheduler.run_events._recover_staging_events"), \
             patch("scheduler.run_events._handle_event", side_effect=fake_handle):
            # Run the loop in a thread so we can stop it
            t = threading.Thread(target=run_event_loop, args=(stop,))
            t.start()
            t.join(timeout=3)

        assert len(processed) == 1
        assert processed[0]["run_id"] == "r1"
        # The staging key must have been cleared
        r.lrem.assert_called_once_with("run_events:prod:processing", 1, raw)

    def test_loop_clears_staging_even_on_handler_exception(self):
        """If _handle_event raises, the raw event must still be removed from
        the staging queue (it will be re-delivered safe because handlers are
        idempotent)."""
        raw = json.dumps({"type": "run_start", "run_id": "r1", "job_id": "j1"}).encode()
        r = MagicMock()
        r.smembers.return_value = ["prod"]

        call_count = [0]

        def rpoplpush_side_effect(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return raw
            return None

        r.rpoplpush.side_effect = rpoplpush_side_effect

        stop = threading.Event()

        def fake_handle(payload):
            stop.set()
            raise RuntimeError("simulated processing failure")

        with patch("scheduler.run_events.get_redis", return_value=r), \
             patch("scheduler.run_events._recover_staging_events"), \
             patch("scheduler.run_events._handle_event", side_effect=fake_handle):
            t = threading.Thread(target=run_event_loop, args=(stop,))
            t.start()
            t.join(timeout=3)

        # Staging must be cleared even after an exception
        r.lrem.assert_called_with("run_events:prod:processing", 1, raw)


def test_handle_event_logs_unknown_type():
    """Unknown event types should log a warning rather than being silently dropped."""
    import logging

    with patch("scheduler.run_events.log") as mock_log:
        _handle_event({"type": "totally_unknown"})
        mock_log.warning.assert_called_once()
        assert "Unknown run event type" in mock_log.warning.call_args[0][0]
