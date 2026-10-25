"""What happens when a run reaches a terminal state: retry, dependents, failure webhooks.

The decision itself is the full edition's (``scheduler.utils.post_run.decide_post_run``); this module only
performs it against the SQLite store. ``finalize_run`` runs the follow-ups exactly once per run.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta
from typing import Optional

from scheduler.utils.notifications import WEBHOOK_MAX_ERROR_LEN, fire_webhooks_async
from scheduler.utils.post_run import FINAL_FAILURE, RETRY, TRIGGER_DEPENDENTS, decide_post_run

from .logs import LogStore
from .store import NotFound, Store
from .store.store import now_utc

log = logging.getLogger("hydra_lite.lifecycle")


class Lifecycle:
    def __init__(self, store: Store, logs: LogStore, wake: Optional[threading.Event] = None):
        self.store = store
        self.logs = logs
        self.wake = wake or threading.Event()

    def finalize(
        self,
        run_id: str,
        status: str,
        returncode: Optional[int] = None,
        reason: Optional[str] = None,
        attempt: Optional[int] = None,
        event_type: Optional[str] = None,
        timings: Optional[dict] = None,
    ) -> dict:
        run, changed = self.store.finish_run(run_id, status, returncode, reason, attempt, event_type, timings)
        if changed:
            try:
                self._follow_up(run)
            except Exception:  # a follow-up bug must never wedge the worker
                log.exception("post-run actions failed for run %s", run_id)
        return run

    def publish_artifact(self, run: dict, name: str, metadata: dict) -> list[str]:
        """Record an artifact a run published and start every job subscribed to it.

        Same contract as the full edition's ``_handle_artifact_emitted``: subscribers get the metadata as the raw-key
        env var ``HYDRA_UPSTREAM_ARTIFACT_METADATA``. One protection the full edition lacks: the publishing job is not
        re-triggered by its own artifact (that is an unbounded loop).
        """
        self.store.upsert_artifact(name, run["id"], run["job_id"], metadata)
        started = []
        for job in self.store.find_artifact_subscribers(name):
            if job["_id"] == run["job_id"]:
                continue
            queued = self.store.enqueue_run(
                job["_id"],
                trigger="artifact",
                params={"HYDRA_UPSTREAM_ARTIFACT_METADATA": json.dumps(metadata or {})},
                priority=int(job.get("priority", 5)),
            )
            self.store.add_event(
                queued["id"], "triggered_by", {"artifact": name, "upstream_run": run["id"], "upstream_job": run["job_id"]}
            )
            started.append(queued["id"])
        if started:
            self.wake.set()
        return started

    def recover_orphans(self) -> int:
        """Fail runs orphaned by a crash/restart and route them through the normal follow-ups."""
        recovered = self.store.recover_orphans()
        for run in recovered:
            try:
                self._follow_up(run)
            except Exception:
                log.exception("post-run actions failed for orphaned run %s", run["id"])
        return len(recovered)

    # ------------------------------------------------------------------ internals
    def _job(self, job_id: str) -> Optional[dict]:
        try:
            return self.store.get_job(job_id)
        except NotFound:
            return None

    def _follow_up(self, run: dict) -> None:
        job = self._job(run["job_id"])
        decision = decide_post_run(run["status"], job, int(run.get("retry_attempt") or 0))
        if decision.action == TRIGGER_DEPENDENTS:
            for dep in self.store.find_dependents(run["job_id"]):
                queued = self.store.enqueue_run(dep["_id"], trigger="dependency", priority=int(dep.get("priority", 5)))
                self.store.add_event(queued["id"], "triggered_by", {"upstream_run": run["id"], "upstream_job": run["job_id"]})
            self.wake.set()
        elif decision.action == RETRY and job:
            not_before = now_utc() + timedelta(seconds=decision.delay_seconds) if decision.delay_seconds else None
            retry = self.store.enqueue_run(
                run["job_id"],
                trigger="retry",
                params=run.get("params"),
                priority=int(job.get("priority", 5)),
                retry_attempt=decision.retry_attempt,
                not_before=not_before,
            )
            self.store.add_event(
                run["id"],
                "retry_scheduled",
                {"retry_run": retry["id"], "retry_attempt": decision.retry_attempt, "delay_seconds": decision.delay_seconds},
            )
            self.wake.set()
        elif decision.action == FINAL_FAILURE and job:
            self.alert(job, run, self._failure_text(run))

    def alert(self, job: dict, run: dict, message: str) -> None:
        hooks = job.get("on_failure_webhooks") or []
        if hooks:
            fire_webhooks_async(hooks, job["_id"], run["id"], message[:WEBHOOK_MAX_ERROR_LEN])

    def _failure_text(self, run: dict) -> str:
        text, _ = self.logs.read(run["id"], "err")
        return text[-WEBHOOK_MAX_ERROR_LEN:] or (run.get("completion_reason") or "")
