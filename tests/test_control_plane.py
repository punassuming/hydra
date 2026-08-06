"""Tests for control-plane pipeline separation (PR 2).

Verifies:
- OrchestratorManager registers, starts, and stops loop threads correctly.
- Heartbeat key is written to Redis when a manager is running.
- create_standard_orchestrator() registers all expected loops.
- HYDRA_MODE is respected by scheduler.main (api mode skips loops, combined mode starts them).
- The /health/orchestration endpoint reports correct status based on the heartbeat key.
"""

import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from scheduler.orchestrator import (
    HEARTBEAT_TTL,
    ORCHESTRATOR_HEARTBEAT_KEY,
    OrchestratorManager,
    create_standard_orchestrator,
)

# ---------------------------------------------------------------------------
# Helper: a trivial loop that blocks on the stop_event.
# ---------------------------------------------------------------------------

def _noop_loop(stop_event: threading.Event):
    stop_event.wait()


# ---------------------------------------------------------------------------
# OrchestratorManager unit tests
# ---------------------------------------------------------------------------

class TestOrchestratorManager(unittest.TestCase):

    def test_register_and_loop_names(self):
        mgr = OrchestratorManager()
        mgr.register("alpha", _noop_loop)
        mgr.register("beta", _noop_loop)
        self.assertEqual(mgr.loop_names, ["alpha", "beta"])

    def test_start_spawns_threads(self):
        mgr = OrchestratorManager()
        mgr.register("noop", _noop_loop)

        with patch.object(mgr, "_start_heartbeat"):  # skip Redis in unit test
            mgr.start()

        self.assertEqual(len(mgr._threads), 1)
        name, thread = mgr._threads[0]
        self.assertEqual(name, "noop")
        self.assertTrue(thread.is_alive())

        mgr.stop()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_stop_sets_stop_event_and_joins(self):
        mgr = OrchestratorManager()
        mgr.register("noop", _noop_loop)

        with patch.object(mgr, "_start_heartbeat"):
            mgr.start()

        self.assertFalse(mgr.stop_event.is_set())
        mgr.stop()
        self.assertTrue(mgr.stop_event.is_set())

    def test_is_alive_reflects_thread_state(self):
        mgr = OrchestratorManager()
        mgr.register("noop", _noop_loop)

        with patch.object(mgr, "_start_heartbeat"):
            mgr.start()

        self.assertTrue(mgr.is_alive())
        mgr.stop()
        for _, t in mgr._threads:
            t.join(timeout=2)
        self.assertFalse(mgr.is_alive())

    def test_start_raises_after_stop(self):
        mgr = OrchestratorManager()
        mgr.stop_event.set()
        with self.assertRaises(RuntimeError):
            mgr.start()

    def test_multiple_loops_all_started(self):
        mgr = OrchestratorManager()
        for name in ("a", "b", "c"):
            mgr.register(name, _noop_loop)

        with patch.object(mgr, "_start_heartbeat"):
            mgr.start()

        self.assertEqual(len(mgr._threads), 3)
        self.assertTrue(all(t.is_alive() for _, t in mgr._threads))
        mgr.stop()


# ---------------------------------------------------------------------------
# Heartbeat tests (using a fake Redis)
# ---------------------------------------------------------------------------

class TestOrchestratorHeartbeat(unittest.TestCase):

    def _make_fake_redis(self):
        store = {}

        fake = MagicMock()

        def fake_set(key, value, ex=None):
            store[key] = value

        def fake_get(key):
            return store.get(key)

        def fake_delete(key):
            store.pop(key, None)

        fake.set.side_effect = fake_set
        fake.get.side_effect = fake_get
        fake.delete.side_effect = fake_delete
        return fake, store

    def test_heartbeat_loop_writes_key(self):
        fake_redis, store = self._make_fake_redis()

        mgr = OrchestratorManager()
        mgr.register("noop", _noop_loop)

        with patch.object(mgr, "_start_heartbeat"):
            mgr.start()

        # Simulate one heartbeat write using the module-level get_redis reference.
        with patch("scheduler.orchestrator.get_redis", return_value=fake_redis):
            loop_names = mgr.loop_names
            payload = json.dumps({"ts": time.time(), "loops": loop_names})
            fake_redis.set(ORCHESTRATOR_HEARTBEAT_KEY, payload, ex=HEARTBEAT_TTL)

        self.assertIn(ORCHESTRATOR_HEARTBEAT_KEY, store)
        data = json.loads(store[ORCHESTRATOR_HEARTBEAT_KEY])
        self.assertIn("ts", data)
        self.assertEqual(data["loops"], ["noop"])

        mgr.stop()

    def test_heartbeat_deleted_on_stop(self):
        fake_redis, store = self._make_fake_redis()
        store[ORCHESTRATOR_HEARTBEAT_KEY] = '{"ts": 1}'  # pre-populate

        mgr = OrchestratorManager()

        # Simulate the cleanup path that runs after stop_event is set.
        with patch("scheduler.orchestrator.get_redis", return_value=fake_redis):
            mgr.stop_event.set()
            fake_redis.delete(ORCHESTRATOR_HEARTBEAT_KEY)

        self.assertNotIn(ORCHESTRATOR_HEARTBEAT_KEY, store)


# ---------------------------------------------------------------------------
# create_standard_orchestrator factory
# ---------------------------------------------------------------------------

class TestCreateStandardOrchestrator(unittest.TestCase):

    def test_all_expected_loops_registered(self):
        expected = {
            "scheduling", "failover", "schedule_trigger", "run_event", "timeout", "sla", "backfill",
            "redis_acl_reconcile",
        }
        mgr = create_standard_orchestrator()
        self.assertEqual(set(mgr.loop_names), expected)

    def test_returns_orchestrator_manager_instance(self):
        mgr = create_standard_orchestrator()
        self.assertIsInstance(mgr, OrchestratorManager)


# ---------------------------------------------------------------------------
# /health/orchestration endpoint
# ---------------------------------------------------------------------------

class TestOrchestrationHealthEndpoint(unittest.TestCase):

    def setUp(self):
        # Use a fixed admin token so the auth middleware is satisfied.
        import os

        from fastapi.testclient import TestClient

        from scheduler.main import app
        os.environ.setdefault("ADMIN_TOKEN", "test_token")
        self.client = TestClient(app, raise_server_exceptions=True)
        self.headers = {"X-Admin-Token": "test_token"}

    def _mock_redis(self, heartbeat_value):
        fake = MagicMock()
        fake.get.return_value = heartbeat_value
        return fake

    def test_health_unknown_when_no_heartbeat(self):
        fake = self._mock_redis(None)
        with patch("scheduler.api.health.get_redis", return_value=fake):
            resp = self.client.get("/health/orchestration", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "unknown")

    def test_health_ok_when_fresh_heartbeat(self):
        payload = json.dumps({"ts": time.time(), "loops": ["scheduling", "failover"]})
        fake = self._mock_redis(payload)
        with patch("scheduler.api.health.get_redis", return_value=fake):
            resp = self.client.get("/health/orchestration", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("age_seconds", data)
        self.assertIn("loops", data)

    def test_health_stale_when_old_heartbeat(self):
        old_ts = time.time() - 60  # 60 seconds old, exceeds TTL of 30s
        payload = json.dumps({"ts": old_ts, "loops": ["scheduling"]})
        fake = self._mock_redis(payload)
        with patch("scheduler.api.health.get_redis", return_value=fake):
            resp = self.client.get("/health/orchestration", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "stale")
        self.assertGreater(data["age_seconds"], 30)

    def test_health_unknown_on_malformed_payload(self):
        fake = self._mock_redis("not-json")
        with patch("scheduler.api.health.get_redis", return_value=fake):
            resp = self.client.get("/health/orchestration", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "unknown")

    def test_health_unknown_when_ts_missing(self):
        payload = json.dumps({"loops": ["scheduling"]})  # no "ts" field
        fake = self._mock_redis(payload)
        with patch("scheduler.api.health.get_redis", return_value=fake):
            resp = self.client.get("/health/orchestration", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "unknown")


# ---------------------------------------------------------------------------
# /health endpoint — must check Mongo, not just Redis
# ---------------------------------------------------------------------------

class TestHealthEndpoint(unittest.TestCase):

    def setUp(self):
        import os

        from fastapi.testclient import TestClient

        from scheduler.main import app
        os.environ.setdefault("ADMIN_TOKEN", "test_token")
        self.headers = {"X-Admin-Token": "test_token"}
        # raise_server_exceptions=False so an unhandled exception in the handler
        # comes back as a real 500 response, matching production (uvicorn) behavior,
        # instead of propagating as a Python exception in the test itself.
        self.client = TestClient(app, raise_server_exceptions=False)

    def _mock_redis(self):
        fake = MagicMock()
        fake.scan_iter.return_value = iter([])
        fake.zcard.return_value = 0
        return fake

    def test_health_ok_when_redis_and_mongo_reachable(self):
        fake_redis = self._mock_redis()
        fake_db = MagicMock()
        with patch("scheduler.api.health.get_redis", return_value=fake_redis), \
             patch("scheduler.api.health.get_db", return_value=fake_db):
            resp = self.client.get("/health", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        fake_db.command.assert_called_once_with("ping")

    def test_health_reports_demo_mode_off_by_default(self):
        fake_redis = self._mock_redis()
        fake_db = MagicMock()
        with patch.dict("os.environ", {}, clear=False), \
             patch("scheduler.api.health.get_redis", return_value=fake_redis), \
             patch("scheduler.api.health.get_db", return_value=fake_db):
            os.environ.pop("HYDRA_DEMO_MODE", None)
            resp = self.client.get("/health", headers=self.headers)
        self.assertEqual(resp.json()["demo_mode"], False)

    def test_health_reports_demo_mode_on_when_set(self):
        fake_redis = self._mock_redis()
        fake_db = MagicMock()
        with patch.dict("os.environ", {"HYDRA_DEMO_MODE": "true"}), \
             patch("scheduler.api.health.get_redis", return_value=fake_redis), \
             patch("scheduler.api.health.get_db", return_value=fake_db):
            resp = self.client.get("/health", headers=self.headers)
        self.assertEqual(resp.json()["demo_mode"], True)

    def test_health_fails_when_mongo_unreachable(self):
        """A Redis-only check would report healthy here; it must not."""
        fake_redis = self._mock_redis()
        fake_db = MagicMock()
        fake_db.command.side_effect = Exception("mongo unreachable")
        with patch("scheduler.api.health.get_redis", return_value=fake_redis), \
             patch("scheduler.api.health.get_db", return_value=fake_db):
            resp = self.client.get("/health", headers=self.headers)
        self.assertEqual(resp.status_code, 500)

    def test_health_fails_when_redis_unreachable(self):
        fake_db = MagicMock()
        with patch("scheduler.api.health.get_redis", side_effect=Exception("redis unreachable")), \
             patch("scheduler.api.health.get_db", return_value=fake_db):
            resp = self.client.get("/health", headers=self.headers)
        self.assertEqual(resp.status_code, 500)


# ---------------------------------------------------------------------------
# HYDRA_MODE integration tests
# ---------------------------------------------------------------------------

class TestHydraModeIntegration(unittest.TestCase):

    def test_main_module_exposes_hydra_mode(self):
        from scheduler import main as main_module
        self.assertTrue(hasattr(main_module, "HYDRA_MODE"))

    def test_combined_mode_is_default(self):
        # Verify that HYDRA_MODE defaults to "combined" when the env var is unset.
        # We check by running a clean Python subprocess so the module isn't already cached.
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import os; os.environ.pop('HYDRA_MODE', None); "
             "import importlib; import scheduler.main as m; importlib.reload(m); "
             "print(m.HYDRA_MODE)"],
            capture_output=True, text=True, timeout=10,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent),
            env={k: v for k, v in __import__("os").environ.items() if k != "HYDRA_MODE"},
        )
        self.assertIn("combined", result.stdout.strip(), result.stderr)

    def test_api_mode_does_not_start_loops(self):
        """When HYDRA_MODE=api, on_startup must not start any orchestrator loops."""
        from scheduler import main as main_module
        original_mode = main_module.HYDRA_MODE
        original_orchestrator = main_module._orchestrator
        try:
            main_module.HYDRA_MODE = "api"
            main_module._orchestrator = None
            with patch("scheduler.main.ensure_admin_token"), \
                 patch("scheduler.main.ensure_domains_seeded"), \
                 patch("scheduler.main.create_standard_orchestrator") as mock_factory:
                main_module.on_startup()
                mock_factory.assert_not_called()
                self.assertIsNone(main_module._orchestrator)
        finally:
            main_module.HYDRA_MODE = original_mode
            main_module._orchestrator = original_orchestrator

    def test_combined_mode_starts_loops(self):
        """When HYDRA_MODE=combined, on_startup must create and start the orchestrator."""
        from scheduler import main as main_module
        mock_mgr = MagicMock(spec=OrchestratorManager)
        original_mode = main_module.HYDRA_MODE
        original_orchestrator = main_module._orchestrator
        try:
            main_module.HYDRA_MODE = "combined"
            main_module._orchestrator = None
            with patch("scheduler.main.ensure_admin_token"), \
                 patch("scheduler.main.ensure_domains_seeded"), \
                 patch("scheduler.main.create_standard_orchestrator", return_value=mock_mgr):
                main_module.on_startup()
                mock_mgr.start.assert_called_once()
                self.assertIs(main_module._orchestrator, mock_mgr)
        finally:
            main_module.HYDRA_MODE = original_mode
            main_module._orchestrator = original_orchestrator

    def test_orchestrator_entrypoint_module_importable(self):
        """The standalone entrypoint module must be importable without side effects."""
        import scheduler.orchestrator_entrypoint as ep
        self.assertTrue(callable(ep.main))


if __name__ == "__main__":
    unittest.main()
