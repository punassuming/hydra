"""Orchestration bootstrap for Hydra's control-plane loops.

Provides ``OrchestratorManager``, a lightweight registry for background
reconciliation threads (scheduling, dispatch, failover, event ingestion,
timeout/SLA/backfill monitoring).

Usage — combined mode (API + orchestrator in one process, the default):

    mgr = create_standard_orchestrator()
    mgr.start()          # starts loops + heartbeat thread
    ...
    mgr.stop()           # signals stop_event and joins threads

Usage — API-only mode (``HYDRA_MODE=api``):
    # Don't create or start a manager; the standalone orchestrator process
    # runs the loops and writes the heartbeat independently.

The manager also writes a lightweight heartbeat key to Redis
(``hydra:orchestrator:heartbeat``) so operators and the ``/health/orchestration``
endpoint can distinguish "API is up" from "orchestration is healthy".
"""

import json
import threading
import time
from typing import Callable, List, Tuple

from .redis_client import get_redis
from .utils.logging import setup_logging

log = setup_logging("scheduler.orchestrator")

# Redis key written by the running orchestrator.
ORCHESTRATOR_HEARTBEAT_KEY = "hydra:orchestrator:heartbeat"
# How often (seconds) the heartbeat is refreshed.
HEARTBEAT_INTERVAL = 10
# TTL (seconds) set on the Redis key; if the process dies the key expires.
HEARTBEAT_TTL = 30


class OrchestratorManager:
    """Manages a set of named background loop threads.

    Each loop function must accept a single argument — a :class:`threading.Event`
    — and return when that event is set.

    The manager also runs a heartbeat thread that periodically writes a
    JSON payload to ``hydra:orchestrator:heartbeat`` in Redis so the
    health endpoint can report orchestration status independently of API
    availability.
    """

    def __init__(self) -> None:
        self._loops: List[Tuple[str, Callable]] = []
        self._threads: List[Tuple[str, threading.Thread]] = []
        self.stop_event: threading.Event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, fn: Callable) -> "OrchestratorManager":
        """Register a loop function under *name*. Returns self for chaining."""
        self._loops.append((name, fn))
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all registered loops and the heartbeat writer."""
        if self.stop_event.is_set():
            raise RuntimeError("OrchestratorManager.start() called after stop_event is already set")
        for name, fn in self._loops:
            t = threading.Thread(target=fn, args=(self.stop_event,), daemon=True, name=f"orchestrator-{name}")
            t.start()
            self._threads.append((name, t))
        log.info(
            "Orchestration loops started (%d): %s",
            len(self._threads),
            [n for n, _ in self._threads],
        )
        self._start_heartbeat()

    def stop(self, join_timeout: float = 2.0) -> None:
        """Signal all loops to stop and wait for them to finish."""
        log.info("Stopping orchestration loops")
        self.stop_event.set()
        for _name, t in self._threads:
            t.join(timeout=join_timeout)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def loop_names(self) -> List[str]:
        return [n for n, _ in self._loops]

    def is_alive(self) -> bool:
        """Return True if at least one loop thread is still running."""
        return any(t.is_alive() for _, t in self._threads)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="orchestrator-heartbeat",
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        loop_names = self.loop_names
        while not self.stop_event.is_set():
            try:
                payload = json.dumps({"ts": time.time(), "loops": loop_names})
                get_redis().set(ORCHESTRATOR_HEARTBEAT_KEY, payload, ex=HEARTBEAT_TTL)
            except Exception as exc:
                log.warning("Orchestrator heartbeat write failed: %s", exc)
            self.stop_event.wait(HEARTBEAT_INTERVAL)
        # Clear heartbeat on clean shutdown so stale data is not left behind.
        try:
            get_redis().delete(ORCHESTRATOR_HEARTBEAT_KEY)
        except Exception:
            log.exception("Failed to clear orchestrator heartbeat during shutdown")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_standard_orchestrator() -> OrchestratorManager:
    """Return an ``OrchestratorManager`` pre-loaded with all standard loops.

    Loops registered:

    * **scheduling** — dispatch pending jobs from the domain queue to workers
    * **failover** — requeue jobs from offline workers; prune stale worker records
    * **schedule_trigger** — advance cron/interval schedules and enqueue due runs
    * **run_event** — consume ``run_events:<domain>`` from Redis → persist to MongoDB
    * **timeout** — mark stale running jobs as failed
    * **sla** — check SLA deadlines and emit alerts
    * **backfill** — dispatch historical backfill runs
    """
    from .run_events import run_event_loop
    from .scheduler import (
        backfill_dispatch_loop,
        failover_loop,
        schedule_trigger_loop,
        scheduling_loop,
        sla_monitoring_loop,
        timeout_enforcement_loop,
    )

    mgr = OrchestratorManager()
    mgr.register("scheduling", scheduling_loop)
    mgr.register("failover", failover_loop)
    mgr.register("schedule_trigger", schedule_trigger_loop)
    mgr.register("run_event", run_event_loop)
    mgr.register("timeout", timeout_enforcement_loop)
    mgr.register("sla", sla_monitoring_loop)
    mgr.register("backfill", backfill_dispatch_loop)
    return mgr
