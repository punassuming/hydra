"""FastAPI app for the lite edition, wire-compatible with the subset of the main API used by hydra-ctl."""

from __future__ import annotations

import hmac
import json
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from scheduler.models.run_params import RunJobRequest

from .. import __version__
from ..jobs import JobValidationError, build_job, merge_update, to_api, validate_payload, with_schedule_enabled
from ..serialize import run_to_api, worker_to_api
from ..store import DuplicateJobName, NotFound
from ..store.store import TERMINAL_STATUSES
from .runtime import Daemon

UNSUPPORTED_PREFIXES = ("/admin", "/domain", "/credentials", "/ai", "/investigations", "/events")
OPEN_PATHS = {"/health"}


def create_app(daemon: Daemon, manage_lifecycle: bool = True) -> FastAPI:
    store, logs, pool, lifecycle = daemon.store, daemon.logs, daemon.pool, daemon.lifecycle

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if manage_lifecycle:
            daemon.start()
        try:
            yield
        finally:
            if manage_lifecycle:
                daemon.shutdown()

    app = FastAPI(title="Hydra (lite edition)", version=__version__, lifespan=lifespan)
    app.state.daemon = daemon

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if request.url.path in OPEN_PATHS:
            return await call_next(request)
        supplied = request.headers.get("x-api-key") or ""
        bearer = request.headers.get("authorization", "")
        if not supplied and bearer.lower().startswith("bearer "):
            supplied = bearer[7:]
        if not supplied or not hmac.compare_digest(supplied.encode(), daemon.token.encode()):
            return JSONResponse({"detail": "invalid or missing API token"}, status_code=401)
        return await call_next(request)

    # ---------------------------------------------------------------- helpers
    def job_or_404(job_id: str) -> dict:
        try:
            return store.get_job(job_id)
        except NotFound:
            raise HTTPException(404, "job not found") from None

    def run_or_404(run_id: str) -> dict:
        try:
            return store.get_run(run_id)
        except NotFound:
            raise HTTPException(404, "run not found") from None

    def job_for(run: dict) -> Optional[dict]:
        try:
            return store.get_job(run["job_id"])
        except NotFound:
            return None

    def queue_run(job: dict, trigger: str, params: Optional[dict] = None) -> dict:
        run = store.enqueue_run(job["_id"], trigger=trigger, params=params, priority=int(job.get("priority", 5)))
        pool.wake.set()
        return run

    def build_or_422(payload: dict) -> dict:
        try:
            return build_job(payload)
        except ValidationError as exc:
            raise HTTPException(422, json.loads(exc.json())) from exc
        except JobValidationError as exc:
            raise HTTPException(422, exc.errors) from exc

    # ----------------------------------------------------------------- health
    @app.get("/health")
    def health():
        queued = store.count_runs("pending")
        return {
            "status": "ok",
            "edition": "lite",
            "mode": daemon.config.mode,
            "version": __version__,
            "workers": len(store.list_workers()),
            "pending_jobs": queued,
            "demo_mode": False,
        }

    @app.get("/health/orchestration")
    def orchestration():
        alive = not daemon.stop.is_set()
        return {"status": "ok" if alive else "stopping", "mode": "embedded", "alive": alive}

    # ------------------------------------------------------------------- jobs
    @app.get("/jobs/")
    def list_jobs(search: Optional[str] = None, tags: Optional[str] = None, limit: int = 1000):
        jobs = store.list_jobs(limit=10000)
        if search:
            needle = search.lower()
            jobs = [j for j in jobs if needle in j["name"].lower() or needle in j["_id"].lower()]
        if tags:
            wanted = {t.strip() for t in tags.split(",") if t.strip()}
            jobs = [j for j in jobs if wanted & set(j.get("tags") or [])]
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
        return [to_api(j) for j in jobs[:limit]]

    @app.post("/jobs/validate")
    def validate_new(payload: Dict[str, Any] = Body(...)):
        try:
            return validate_payload(payload)
        except ValidationError as exc:
            return {
                "valid": False,
                "errors": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()],
                "next_run_at": None,
            }

    @app.post("/jobs/")
    def submit_job(payload: Dict[str, Any] = Body(...)):
        doc = build_or_422(payload)
        try:
            job = store.create_job(doc, changed_by="api")
        except DuplicateJobName:
            raise HTTPException(409, f"a job named {doc['name']!r} already exists") from None
        if job["schedule"]["mode"] == "immediate" and not job.get("depends_on"):
            queue_run(job, "immediate_submit")
        return to_api(job)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return to_api(job_or_404(job_id))

    @app.put("/jobs/{job_id}")
    def update_job(job_id: str, patch: Dict[str, Any] = Body(...)):
        existing = job_or_404(job_id)
        try:
            doc = merge_update(existing, patch)
        except ValidationError as exc:
            raise HTTPException(422, json.loads(exc.json())) from exc
        except JobValidationError as exc:
            raise HTTPException(422, exc.errors) from exc
        try:
            return to_api(store.update_job(job_id, doc, changed_by="api"))
        except DuplicateJobName:
            raise HTTPException(409, "a job with that name already exists") from None

    @app.delete("/jobs/{job_id}")
    def delete_job(job_id: str):
        job_or_404(job_id)
        store.delete_job(job_id)
        return {"job_id": job_id, "deleted": True}

    @app.post("/jobs/{job_id}/validate")
    def validate_existing(job_id: str):
        job = job_or_404(job_id)
        return validate_payload({k: v for k, v in job.items() if k not in ("_id", "created_at", "updated_at", "enabled")})

    @app.post("/jobs/{job_id}/run")
    def run_now(job_id: str, body: RunJobRequest = Body(default=RunJobRequest())):
        job = job_or_404(job_id)
        run = queue_run(job, "manual", body.params or None)
        return {"job_id": job_id, "queued": True, "run_id": run["id"]}

    def set_enabled(job_id: str, enabled: bool) -> dict:
        job = job_or_404(job_id)
        doc = with_schedule_enabled(job, enabled)
        return to_api(store.update_job(job_id, doc, changed_by="api"))

    @app.post("/jobs/{job_id}/enable")
    def enable_job(job_id: str):
        return set_enabled(job_id, True)

    @app.post("/jobs/{job_id}/disable")
    def disable_job(job_id: str):
        return set_enabled(job_id, False)

    @app.get("/jobs/{job_id}/runs")
    def job_runs(job_id: str, limit: int = 100):
        job = job_or_404(job_id)
        return [run_to_api(r, job, logs, full=False) for r in store.list_runs(job_id=job_id, limit=limit)]

    @app.get("/jobs/{job_id}/versions")
    def job_versions(job_id: str):
        return store.list_versions(job_id)

    @app.get("/jobs/{job_id}/versions/{version}")
    def job_version(job_id: str, version: int):
        try:
            return store.get_version(job_id, version)
        except NotFound:
            raise HTTPException(404, "version not found") from None

    @app.post("/jobs/{job_id}/backfill")
    def backfill(job_id: str):
        raise HTTPException(501, "backfill is not supported by this Hydra edition yet")

    # ------------------------------------------------------------------- runs
    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        run = run_or_404(run_id)
        return run_to_api(run, job_for(run), logs)

    @app.get("/runs/{run_id}/logs")
    def run_logs(run_id: str, out_offset: int = 0, err_offset: int = 0):
        run = run_or_404(run_id)
        out, out_next = logs.read(run_id, "out", out_offset)
        err, err_next = logs.read(run_id, "err", err_offset)
        return {
            "stdout": out,
            "stderr": err,
            "out_offset": out_next,
            "err_offset": err_next,
            "done": run["status"] in TERMINAL_STATUSES,
        }

    @app.get("/runs/{run_id}/stream")
    def stream_run(run_id: str):
        run_or_404(run_id)

        def events():
            out_off = err_off = 0
            while not daemon.stop.is_set():
                out, out_off = logs.read(run_id, "out", out_off)
                err, err_off = logs.read(run_id, "err", err_off)
                for stream, text in (("stdout", out), ("stderr", err)):
                    if text:
                        yield f"event: log_chunk\ndata: {json.dumps({'stream': stream, 'text': text})}\n\n"
                if store.get_run(run_id)["status"] in TERMINAL_STATUSES:
                    # one final drain so lines written just before the state flip are not lost
                    out, out_off = logs.read(run_id, "out", out_off)
                    err, err_off = logs.read(run_id, "err", err_off)
                    for stream, text in (("stdout", out), ("stderr", err)):
                        if text:
                            yield f"event: log_chunk\ndata: {json.dumps({'stream': stream, 'text': text})}\n\n"
                    yield f"event: run_end\ndata: {json.dumps({'run_id': run_id})}\n\n"
                    return
                time.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/kill")
    def kill_run(run_id: str):
        run = run_or_404(run_id)
        if run["status"] in TERMINAL_STATUSES:
            raise HTTPException(404, "run not found or not currently running")
        if run["status"] == "pending":
            lifecycle.finalize(run_id, "failed", reason="killed while pending", event_type="killed")
        elif not pool.kill(run_id):
            raise HTTPException(404, "run not found or not currently running")
        return {"run_id": run_id, "signal": "kill_sent"}

    @app.get("/history/")
    def history(limit: int = 1000, search: Optional[str] = None, paged: bool = False, cursor: Optional[str] = None):
        runs = store.list_runs(limit=min(limit, 5000) if not paged else min(max(limit, 1), 200) + 1, before=cursor)
        jobs: dict[str, Optional[dict]] = {}

        def lookup(run: dict) -> Optional[dict]:
            if run["job_id"] not in jobs:
                jobs[run["job_id"]] = job_for(run)
            return jobs[run["job_id"]]

        rows = [run_to_api(r, lookup(r), logs, full=False) for r in runs]
        if search:
            needle = search.lower()
            rows = [r for r in rows if needle in (r.get("job_name") or "").lower() or needle in r["_id"]]
        if not paged:
            return rows
        page_size = min(max(limit, 1), 200)
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return {"items": rows, "has_more": has_more, "next_cursor": runs[page_size - 1]["queued_at"] if has_more else None}

    # ---------------------------------------------------------------- workers
    @app.get("/workers/")
    def list_workers():
        jobs, users = pool.active()
        return [worker_to_api(w, jobs, users) if w["id"] == pool.worker_id else worker_to_api(w) for w in store.list_workers()]

    @app.post("/workers/{worker_id}/state")
    def worker_state(worker_id: str, body: Dict[str, str] = Body(...)):
        state = {"disabled": "offline"}.get(body.get("state", ""), body.get("state", ""))
        if state not in {"online", "draining", "offline"}:
            raise HTTPException(422, "state must be online, draining or offline")
        try:
            store.set_worker_state(worker_id, state)
        except NotFound:
            raise HTTPException(404, "worker not found") from None
        if worker_id == pool.worker_id:
            pool.state = state
        return {"worker_id": worker_id, "state": state}

    @app.post("/workers/{worker_id}/detach")
    def worker_detach(worker_id: str):
        raise HTTPException(501, "detach is not supported by this Hydra edition")

    # --------------------------------------------------------------- overview
    @app.get("/overview/statistics")
    def overview_statistics():
        counts: dict[str, int] = {}
        for run in store.list_runs(limit=5000):
            counts[run["status"]] = counts.get(run["status"], 0) + 1
        return {"jobs": len(store.list_jobs(limit=10000)), "runs_by_status": counts}

    @app.get("/overview/queue")
    def overview_queue(pending_limit: int = 50, upcoming_limit: int = 50):
        pending = store.list_runs(status="pending", limit=pending_limit)
        upcoming = sorted(
            (j for j in store.list_jobs(limit=10000) if j["enabled"] and (j.get("schedule") or {}).get("next_run_at")),
            key=lambda j: j["schedule"]["next_run_at"],
        )[:upcoming_limit]
        return {
            "pending": [run_to_api(r, job_for(r), logs, full=False) for r in pending],
            "pending_total": store.count_runs("pending"),
            "upcoming": [{"job_id": j["_id"], "name": j["name"], "next_run_at": j["schedule"]["next_run_at"]} for j in upcoming],
        }

    @app.get("/overview/pressure")
    def overview_pressure():
        workers = store.list_workers()
        return {
            "pending": store.count_runs("pending"),
            "running": pool.running,
            "capacity": sum(w["max_concurrency"] for w in workers),
            "online_workers": sum(1 for w in workers if w["state"] == "online"),
        }

    # ----------------------------------------------------------------- system
    @app.get("/system/status")
    def system_status():
        return {"edition": "lite", "version": __version__, "workers": len(store.list_workers()), "running": pool.running}

    @app.post("/system/shutdown")
    def system_shutdown():
        server = getattr(app.state, "server", None)
        if server is None:
            raise HTTPException(409, "daemon was not started by hydra's runner; stop it from its supervisor")
        server.should_exit = True
        return {"shutdown": True}

    # ------------------------------------------------------- unsupported area
    for prefix in UNSUPPORTED_PREFIXES:

        def _unsupported(path: str, _prefix: str = prefix):
            raise HTTPException(501, f"{_prefix} is not supported by this Hydra edition")

        app.add_api_route(
            prefix + "/{path:path}", _unsupported, methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False
        )

    return app
