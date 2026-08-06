"""Tests for the Redis ACL reconciliation loop.

ACL SETUSER is in-memory only (no aclfile configured), so a Redis restart
wipes every worker ACL user. Previously that was only restored at scheduler
*process* startup (ensure_domains_seeded), which left worker auth broken
after a Redis-only restart until an operator noticed. This loop makes that
self-healing — see scheduler/scheduler.py::redis_acl_reconciliation_loop.
"""

import threading
from unittest.mock import MagicMock, patch

from scheduler.scheduler import _reconcile_domain_acls, redis_acl_reconciliation_loop


def test_reconcile_domain_acls_reapplies_every_domain_with_a_password():
    db = MagicMock()
    db.domains.find.return_value = [
        {"domain": "prod", "worker_redis_acl_password": "pw-prod"},
        {"domain": "staging", "worker_redis_acl_password": "pw-staging"},
        {"domain": "no-password-yet", "worker_redis_acl_password": None},
        {"domain": None, "worker_redis_acl_password": "orphaned"},
    ]

    with patch("scheduler.utils.redis_acl.ensure_worker_acl_user") as mock_ensure:
        reconciled = _reconcile_domain_acls(db)

    assert reconciled == 2
    mock_ensure.assert_any_call("prod", password="pw-prod")
    mock_ensure.assert_any_call("staging", password="pw-staging")
    assert mock_ensure.call_count == 2


def test_reconcile_domain_acls_continues_past_a_failing_domain():
    db = MagicMock()
    db.domains.find.return_value = [
        {"domain": "broken", "worker_redis_acl_password": "pw-broken"},
        {"domain": "fine", "worker_redis_acl_password": "pw-fine"},
    ]

    def _side_effect(domain, password=None):
        if domain == "broken":
            raise ConnectionError("redis unreachable")
        return {"username": domain, "password": password}

    with patch("scheduler.utils.redis_acl.ensure_worker_acl_user", side_effect=_side_effect) as mock_ensure:
        reconciled = _reconcile_domain_acls(db)

    assert reconciled == 1
    assert mock_ensure.call_count == 2


def test_loop_reconciles_once_per_wait_interval_then_stops():
    stop_event = threading.Event()
    calls = []

    def _fake_wait(_timeout):
        calls.append("wait")
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._reconcile_domain_acls") as mock_reconcile:
        redis_acl_reconciliation_loop(stop_event)

    mock_reconcile.assert_called_once()
    assert calls == ["wait"]


def test_loop_survives_reconcile_exception():
    stop_event = threading.Event()

    def _fake_wait(_timeout):
        stop_event.set()
        return True

    stop_event.wait = _fake_wait

    with patch("scheduler.scheduler.get_db", return_value=MagicMock()), \
         patch("scheduler.scheduler._reconcile_domain_acls", side_effect=RuntimeError("boom")):
        # Must not raise — the loop logs and keeps going.
        redis_acl_reconciliation_loop(stop_event)
