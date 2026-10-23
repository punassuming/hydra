"""The worker protocol: how subprocess workers talk to the daemon.

Event payloads are the full edition's own ``run_start`` / ``run_end`` dicts (see ``worker/worker.py``), so a
worker implementation only has to learn one shape. Lite adds two optional keys on ``run_end``: ``event_type``
(``killed``) and ``timings``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from scheduler.models.job_run import TERMINAL_STATES
from scheduler.utils.affinity import normalize_affinity, passes_affinity
from worker.protocol import WORKER_PROTOCOL_VERSION

from ..loops import reconcile_worker
from ..store import NotFound
from ..store.store import iso, now_utc
from ..worker.router import split_csv, worker_view
from .runtime import Daemon

log = logging.getLogger("hydra_lite.internal")

MAX_CLAIM_WAIT_SECONDS = 20.0


class RegisterBody(BaseModel):
    worker_id: str
    max_concurrency: int = 1
    meta: Dict[str, Any] = Field(default_factory=dict)


class ClaimBody(BaseModel):
    worker_id: str
    capacity: int = 1  # free normal slots
    bypass: int = 0  # extra slots the worker will give bypass_concurrency jobs while it is at capacity
    wait: float = 15.0


class HeartbeatBody(BaseModel):
    worker_id: str
    running_run_ids: List[str] = Field(default_factory=list)


class LogChunk(BaseModel):
    run_id: str
    stream: str
    text: str


class LogsBody(BaseModel):
    chunks: List[LogChunk]


def register_internal(app: FastAPI, daemon: Daemon) -> None:
    store, lifecycle, logs, router = daemon.store, daemon.lifecycle, daemon.logs, daemon.router
    warned: set[tuple[str, str]] = set()

    @app.post("/internal/register")
    def register(body: RegisterBody):
        meta = dict(body.meta)
        version = meta.get("worker_protocol_version")
        if version != WORKER_PROTOCOL_VERSION and (body.worker_id, str(version)) not in warned:
            warned.add((body.worker_id, str(version)))
            log.warning("worker %s reports protocol %r; daemon speaks %r", body.worker_id, version, WORKER_PROTOCOL_VERSION)
        store.register_worker(
            body.worker_id,
            pid=meta.get("pid"),
            max_concurrency=max(1, body.max_concurrency),
            tags=split_csv(meta.get("tags")),
            capabilities=split_csv(meta.get("capabilities")),
            meta=meta,
        )
        # A process that (re)registers holds nothing: recover whatever its previous incarnation was running.
        reconcile_worker(store, lifecycle, body.worker_id, set(), grace=False)
        return {"state": store.get_worker(body.worker_id)["state"], "protocol_version": WORKER_PROTOCOL_VERSION}

    def _claim_batch(body: ClaimBody) -> List[dict]:
        try:
            worker = store.get_worker(body.worker_id)
        except NotFound:
            raise HTTPException(404, "worker is not registered") from None
        if worker["state"] != "online" or not store.has_pending():
            return []
        view = worker_view(worker)

        def eligible(job: Optional[dict]) -> bool:
            return job is None or passes_affinity(normalize_affinity(job), view)

        def accept_any(run: dict, job: Optional[dict]) -> bool:
            return eligible(job)

        def accept_bypass(run: dict, job: Optional[dict]) -> bool:
            # a deleted job is claimed so it can be failed promptly; otherwise only bypass_concurrency jobs may exceed capacity
            return job is None or (bool(job.get("bypass_concurrency")) and eligible(job))

        envelopes: List[dict] = []
        # Normal slots first, then bypass_concurrency jobs into the worker's extra room (same semantics as the full
        # edition: a bypass job may run even when the worker is at max_concurrency, up to its soft cap).
        for limit, accept in ((max(0, min(body.capacity, 32)), accept_any), (max(0, min(body.bypass, 32)), accept_bypass)):
            for _ in range(limit):
                run = store.claim_run(body.worker_id, accept=accept)
                if run is None:
                    break
                try:
                    job = store.get_job(run["job_id"])
                except NotFound:
                    lifecycle.finalize(run["id"], "failed", returncode=1, reason="job was deleted before the run started")
                    continue
                envelopes.append(
                    {
                        "run_id": run["id"],
                        "job_id": run["job_id"],
                        "job": job,
                        "params": run["params"],
                        "retry_attempt": run["retry_attempt"],
                        "trigger": run["trigger"],
                        "enqueued_ts": run["queued_at"],
                        "dispatch_ts": iso(now_utc()),
                        "queue_latency_ms": run["queue_latency_ms"],
                    }
                )
        return envelopes

    @app.post("/internal/claim")
    async def claim(body: ClaimBody):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, min(body.wait, MAX_CLAIM_WAIT_SECONDS))
        while True:
            runs = await run_in_threadpool(_claim_batch, body)
            if runs or loop.time() >= deadline or daemon.stop.is_set():
                return {"runs": runs}
            await asyncio.sleep(0.15)

    @app.post("/internal/heartbeat")
    def heartbeat(body: HeartbeatBody):
        try:
            store.heartbeat(body.worker_id)
            worker = store.get_worker(body.worker_id)
        except NotFound:
            raise HTTPException(404, "worker is not registered") from None
        reconcile_worker(store, lifecycle, body.worker_id, set(body.running_run_ids))
        kills = router.kills_for(body.running_run_ids)
        ordered = {k["run_id"] for k in kills}
        for run_id in body.running_run_ids:  # runs the daemon no longer assigns to this worker must stop
            if run_id in ordered:
                continue
            try:
                run = store.get_run(run_id)
                owned = run["worker_id"] == body.worker_id and run["status"] not in TERMINAL_STATES
            except NotFound:
                owned = False
            if not owned:
                kills.append({"run_id": run_id, "reason": "orphaned"})
        stop = worker["state"] == "draining" and not body.running_run_ids and router.stop_requested(body.worker_id)
        return {"state": worker["state"], "kill": kills, "stop": stop}

    @app.post("/internal/events")
    def events(payload: Dict[str, Any]):
        kind, run_id = payload.get("type"), str(payload.get("run_id") or "")
        if not run_id:
            raise HTTPException(422, "run_id is required")
        try:
            run = store.get_run(run_id)
        except NotFound:
            raise HTTPException(404, "run not found") from None
        worker_id = payload.get("worker_id")
        if worker_id and run["worker_id"] != worker_id:
            return {"ok": False, "reason": "run is not assigned to this worker"}
        if kind == "run_start":
            try:
                store.start_run(run_id, log_path=payload.get("log_path"))
            except NotFound:
                return {"ok": False, "reason": f"run is {run['status']}, not dispatched"}
        elif kind == "run_retry":
            store.add_event(run_id, "retry", {"attempt": payload.get("attempt"), "reason": payload.get("reason")})
        elif kind == "run_end":
            status = payload.get("status", "failed")
            if status not in TERMINAL_STATES:
                raise HTTPException(422, f"status must be one of {sorted(TERMINAL_STATES)}")
            lifecycle.finalize(
                run_id,
                status,
                returncode=payload.get("returncode"),
                reason=payload.get("completion_reason"),
                attempt=payload.get("attempt"),
                event_type=payload.get("event_type"),
                timings={k: payload.get(k) for k in ("source_fetch_ms", "env_prep_ms")},
            )
            logs.close_run(run_id)
        else:
            raise HTTPException(422, f"unknown event type {kind!r}")
        return {"ok": True}

    @app.post("/internal/logs")
    def append_logs(body: LogsBody):
        runs: dict[str, dict] = {}
        for chunk in body.chunks:
            if chunk.run_id not in runs:
                try:
                    runs[chunk.run_id] = store.get_run(chunk.run_id)
                except NotFound:
                    continue
            logs.writer(chunk.run_id, runs[chunk.run_id]["queued_at"]).write(
                "out" if chunk.stream == "stdout" else "err", chunk.text
            )
        for run_id, run in runs.items():
            if run["status"] in TERMINAL_STATES:  # a straggler after run_end must not leave a handle open
                logs.close_run(run_id)
        return {"ok": True}
