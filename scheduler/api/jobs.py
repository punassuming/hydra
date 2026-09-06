import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from ..event_bus import event_bus
from ..models.job_definition import (
    JobCreate,
    JobDefinition,
    JobUpdate,
    JobValidationResult,
    ScheduleConfig,
)
from ..models.job_run import JobRun
from ..mongo_client import get_db
from ..redis_client import get_redis
from ..utils.schedule import initialize_schedule

router = APIRouter()


def _apply_retry_count(payload: dict) -> dict:
    """Map the simplified retry_count field to max_retries and strip it."""
    retry_count = payload.pop("retry_count", None)
    if retry_count is not None and not payload.get("max_retries"):
        payload["max_retries"] = retry_count
    return payload

MASKED_SECRET = "********"


def _sanitize_job_response(job: JobDefinition) -> dict:
    """Strip sensitive fields (e.g. connection_uri) from job responses."""
    data = job.model_dump(by_alias=True)
    executor = data.get("executor") or {}
    if executor.get("type") == "sql" and "connection_uri" in executor:
        executor["connection_uri"] = MASKED_SECRET if executor["connection_uri"] else None
    kerberos = executor.get("kerberos") or {}
    if kerberos.get("keytab"):
        kerberos["keytab"] = MASKED_SECRET
    return data


def _fetch_job_runs(job_id: str, domain_filter: str | None = None) -> List[Dict[str, Any]]:
    db = get_db()
    query: Dict[str, Any] = {"job_id": job_id}
    if domain_filter:
        query["domain"] = domain_filter
    runs = list(db.job_runs.find(query).sort("start_ts", 1))
    normalized: List[Dict[str, Any]] = []
    for run in runs:
        doc = _normalize_run_doc(run)
        normalized.append(doc)
    return normalized


def _normalize_run_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(doc)
    if "_id" in normalized:
        normalized["_id"] = str(normalized["_id"])
    stdout = (normalized.get("stdout") or "")[:]
    stderr = (normalized.get("stderr") or "")[:]
    normalized["stdout_tail"] = stdout[-4096:]
    normalized["stderr_tail"] = stderr[-4096:]
    duration = None
    if normalized.get("start_ts") and normalized.get("end_ts"):
        try:
            duration = (normalized["end_ts"] - normalized["start_ts"]).total_seconds()
        except Exception:
            duration = None
    normalized["duration"] = duration
    return normalized


def _enqueue_job(
    job_id: str,
    reason: str,
    extra_payload: dict | None = None,
    priority: int | None = None,
    domain: str = "prod",
    params: dict | None = None,
    retry_attempt: int = 0,
):
    r = get_redis()
    score = float(priority if priority is not None else 5)
    r.sadd("hydra:domains", domain)
    r.zadd(f"job_queue:{domain}:pending", {job_id: score})
    meta_mapping: dict = {"enqueued_ts": time.time(), "reason": reason}
    if params:
        meta_mapping["params"] = json.dumps(params)
    if retry_attempt > 0:
        meta_mapping["retry_attempt"] = str(retry_attempt)
    r.hset(f"job_enqueue_meta:{domain}:{job_id}", mapping=meta_mapping)
    r.expire(f"job_enqueue_meta:{domain}:{job_id}", 24 * 3600)
    payload = {"job_id": job_id, "reason": reason, "priority": score, "domain": domain}
    if extra_payload:
        payload.update(extra_payload)
    event_bus.publish("job_enqueued", payload)


def _validate_job_definition(job: JobDefinition) -> JobValidationResult:
    errors = []
    next_run_at = None
    executor = job.executor
    exec_type = getattr(executor, "type", None)
    if exec_type == "python":
        code = getattr(executor, "code", "")
        if not code.strip():
            errors.append("python executor requires non-empty code")
        else:
            try:
                compile(code, "<job>", "exec")
            except SyntaxError as exc:
                errors.append(
                    f"python code syntax error: {exc.msg} (line {exc.lineno})"
                )
        env_cfg = getattr(executor, "environment", None)
        if env_cfg and env_cfg.type != "venv" and env_cfg.venv_path:
            errors.append(
                "environment.venv_path can only be set when environment.type == 'venv'"
            )
    elif exec_type in {"shell", "batch", "powershell"}:
        script = getattr(executor, "script", "")
        if not script.strip():
            errors.append(f"{exec_type} executor requires non-empty script")
    elif exec_type == "sql":
        query = getattr(executor, "query", "")
        if not query.strip():
            errors.append("sql executor requires a non-empty query")
        connection_uri = getattr(executor, "connection_uri", None) or ""
        credential_ref = getattr(executor, "credential_ref", None) or ""
        if not connection_uri.strip() and not credential_ref.strip():
            errors.append("sql executor requires connection_uri or credential_ref")
    elif exec_type == "external":
        command = getattr(executor, "command", "")
        if not command.strip():
            errors.append("external executor requires a command or binary path")
    elif exec_type == "sensor":
        target = getattr(executor, "target", "")
        if not target.strip():
            errors.append("sensor executor requires a non-empty target")
        sensor_type = getattr(executor, "sensor_type", "")
        if sensor_type == "sql":
            connection_uri = getattr(executor, "connection_uri", None) or ""
            credential_ref = getattr(executor, "credential_ref", None) or ""
            if not connection_uri.strip() and not credential_ref.strip():
                errors.append("sql sensor requires connection_uri or credential_ref")
    else:
        errors.append("executor.type must be one of python|shell|batch|powershell|sql|external|sensor")

    try:
        next_run_at = initialize_schedule(job.schedule, datetime.now(timezone.utc)).next_run_at
    except ValueError as exc:
        errors.append(str(exc))

    return JobValidationResult(valid=not errors, errors=errors, next_run_at=next_run_at)


def _attach_schedule(job_def: JobDefinition, force: bool = False) -> JobDefinition:
    schedule = job_def.schedule
    needs_init = force or (
        schedule.mode != "immediate"
        and schedule.enabled
        and schedule.next_run_at is None
    )
    if not needs_init:
        return job_def
    try:
        new_schedule = initialize_schedule(schedule, datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=[str(exc)])
    return job_def.model_copy(update={"schedule": new_schedule})


@router.get("/jobs/templates")
def list_job_templates():
    from ..examples.templates import TEMPLATES
    return TEMPLATES


@router.get("/jobs/")
def list_jobs(request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    search = request.query_params.get("search")
    tags_param = request.query_params.get("tags")
    
    if is_admin and force_domain:
        query = {"domain": force_domain}
    elif is_admin:
        query = {}
    else:
        query = {"domain": domain}
    
    # Add search filter
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"_id": {"$regex": search, "$options": "i"}},
        ]
    
    # Add tag filter
    if tags_param:
        tags = [t.strip() for t in tags_param.split(",") if t.strip()]
        if tags:
            query["tags"] = {"$in": tags}
    
    docs = list(db.job_definitions.find(query).sort("created_at", -1))
    return [_sanitize_job_response(JobDefinition.model_validate(doc)) for doc in docs]


@router.post("/jobs/", response_model=JobDefinition)
def submit_job(job: JobCreate, request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    payload = _apply_retry_count(job.model_dump())
    payload["domain"] = domain
    job_def = JobDefinition(**payload)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    if job_def.schedule.mode == "immediate":
        _enqueue_job(job_def.id, reason="immediate_submit", priority=job_def.priority, domain=job_def.domain)
    event_bus.publish(
        "job_submitted",
        {
            "job_id": job_def.id,
            "name": job_def.name,
            "user": job_def.user,
            "domain": job_def.domain,
            "schedule_mode": job_def.schedule.mode,
            "next_run_at": (
                job_def.schedule.next_run_at.isoformat()
                if job_def.schedule.next_run_at
                else None
            ),
        },
    )
    return _sanitize_job_response(job_def)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    return _sanitize_job_response(JobDefinition.model_validate(doc))


@router.get("/jobs/{job_id}/runs", response_model=List[JobRun])
def get_job_runs(job_id: str, request: Request):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    force_domain = request.query_params.get("domain")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and job.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    domain_filter = None if (is_admin and not force_domain) else (force_domain or domain)
    runs = _fetch_job_runs(job_id, domain_filter=domain_filter)
    return [JobRun.model_validate(r) for r in runs]


@router.put("/jobs/{job_id}", response_model=JobDefinition)
def update_job(job_id: str, updates: JobUpdate, request: Request):
    db = get_db()
    existing = db.job_definitions.find_one({"_id": job_id})
    if not existing:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and existing.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    update_doc = updates.model_dump(exclude_unset=True)
    if not update_doc:
        raise HTTPException(status_code=400, detail="no fields to update")
    merged = {**existing, **update_doc}
    merged["updated_at"] = datetime.now(timezone.utc)
    job_def = JobDefinition.model_validate(merged)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force="schedule" in update_doc)
    db.job_definitions.replace_one({"_id": job_id}, job_def.to_mongo())
    event_bus.publish("job_updated", {"job_id": job_id, "domain": job_def.domain})
    return _sanitize_job_response(job_def)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    """Delete a job definition and remove any pending queue entries for it.

    Historical runs are preserved; only the definition and pending work are removed.
    """
    db = get_db()
    existing = db.job_definitions.find_one({"_id": job_id})
    if not existing:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    job_domain = existing.get("domain", "prod")
    if not is_admin and job_domain != domain:
        raise HTTPException(status_code=403, detail="forbidden")

    db.job_definitions.delete_one({"_id": job_id})

    r = get_redis()
    r.zrem(f"job_queue:{job_domain}:pending", job_id)
    r.delete(f"job_enqueue_meta:{job_domain}:{job_id}")

    event_bus.publish("job_deleted", {"job_id": job_id, "domain": job_domain, "name": existing.get("name")})
    return {"job_id": job_id, "deleted": True}


@router.post("/jobs/{job_id}/validate", response_model=JobValidationResult)
def validate_job(job_id: str, request: Request):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    job_def = JobDefinition.model_validate(doc)
    return _validate_job_definition(job_def)


@router.post("/jobs/validate", response_model=JobValidationResult)
def validate_payload(job: JobCreate, request: Request):
    domain = getattr(request.state, "domain", "prod")
    payload = job.model_dump()
    payload["domain"] = domain
    job_def = JobDefinition(**payload)
    return _validate_job_definition(job_def)


class RunJobRequest(BaseModel):
    params: Dict[str, str] = {}


@router.post("/jobs/{job_id}/run")
def run_job_now(job_id: str, request: Request, body: RunJobRequest = Body(default=RunJobRequest())):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    priority = doc.get("priority", 5)
    _enqueue_job(
        job_id,
        reason="manual_run",
        priority=priority,
        domain=doc.get("domain", "prod"),
        params=body.params or None,
    )
    event_bus.publish("job_manual_run", {"job_id": job_id, "domain": doc.get("domain", "prod")})
    return {"job_id": job_id, "queued": True}


_MAX_BACKFILL_DAYS = 366


class BackfillRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@router.post("/jobs/{job_id}/backfill")
def backfill_job(job_id: str, body: BackfillRequest, request: Request):
    """Queue a batch of historical runs for a job over a date range.

    For each day between start_date and end_date (inclusive), a run is pushed
    to the backfill queue with HYDRA_EXECUTION_DATE injected as an environment
    variable so the worker script knows which logical partition to process.
    """
    db = get_db()
    r = get_redis()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        start_dt = date.fromisoformat(body.start_date.strip()[:10])
        end_dt = date.fromisoformat(body.end_date.strip()[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="start_date and end_date must be in YYYY-MM-DD format")

    if end_dt < start_dt:
        raise HTTPException(status_code=422, detail="end_date must be >= start_date")

    num_days = (end_dt - start_dt).days + 1
    if num_days > _MAX_BACKFILL_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"backfill range exceeds maximum of {_MAX_BACKFILL_DAYS} days",
        )

    job_domain = doc.get("domain", "prod")
    priority = int(doc.get("priority", 5))
    r.sadd("hydra:domains", job_domain)

    current = start_dt
    queued_count = 0
    while current <= end_dt:
        item = json.dumps({
            "job_id": job_id,
            "execution_date": current.isoformat(),
            "priority": priority,
            "domain": job_domain,
        })
        r.rpush(f"backfill_queue:{job_domain}", item)
        current += timedelta(days=1)
        queued_count += 1

    event_bus.publish(
        "job_backfill",
        {
            "job_id": job_id,
            "domain": job_domain,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "queued_count": queued_count,
        },
    )
    return {
        "job_id": job_id,
        "queued_count": queued_count,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    """Return one run for the shared UI run inspector."""
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    query = {"_id": run_id}
    if not is_admin:
        query["domain"] = domain
    doc = db.job_runs.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="run not found")
    doc["_id"] = str(doc["_id"])
    return doc


@router.post("/runs/{run_id}/kill")
def kill_run(run_id: str, request: Request):
    """Send a kill signal to a currently running job identified by its run_id."""
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    found = False
    scan_domains = [domain] if not is_admin else list(r.smembers("hydra:domains") or [domain])
    for d in scan_domains:
        for key in r.scan_iter(f"job_running:{d}:*"):
            data = r.hgetall(key) or {}
            if data.get("run_id") == run_id:
                # Check domain auth
                if not is_admin and data.get("domain", "prod") != domain:
                    continue
                r.publish(f"job_kill:{d}", run_id)
                found = True
                break
        if found:
            break
    if not found:
        raise HTTPException(status_code=404, detail="run not found or not currently running")
    return {"run_id": run_id, "signal": "kill_sent"}


@router.post("/jobs/adhoc", response_model=JobDefinition)
def run_adhoc_job(job: JobCreate, request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    adhoc_schedule = ScheduleConfig(mode="immediate", enabled=False)
    job_dict = _apply_retry_count(job.model_dump())
    job_dict["schedule"] = adhoc_schedule.model_dump()
    job_dict["domain"] = domain
    job_def = JobDefinition(**job_dict)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    _enqueue_job(job_def.id, reason="adhoc_run", priority=job_def.priority, domain=domain)
    return _sanitize_job_response(job_def)


@router.get("/overview/jobs")
def jobs_overview(request: Request):
    db = get_db()
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    if is_admin and force_domain:
        query = {"domain": force_domain}
    elif is_admin:
        query = {}
    else:
        query = {"domain": domain}
    job_docs = list(db.job_definitions.find(query))
    overview = []
    for job in job_docs:
        job_id = job["_id"]
        total_runs = db.job_runs.count_documents({"job_id": job_id})
        success_runs = db.job_runs.count_documents(
            {"job_id": job_id, "status": "success"}
        )
        failed_runs = db.job_runs.count_documents(
            {"job_id": job_id, "status": "failed"}
        )
        queued = 1 if r.zscore(f"job_queue:{job.get('domain','prod')}:pending", job_id) is not None else 0
        recent_runs_cursor = (
            db.job_runs.find({"job_id": job_id})
            .sort("start_ts", -1)
            .limit(12)
        )
        recent_runs = [_normalize_run_doc(run) for run in recent_runs_cursor]
        last_run_doc = recent_runs[0] if recent_runs else None
        
        # Calculate average duration from successful runs
        avg_duration = None
        completed_runs = list(db.job_runs.find(
            {"job_id": job_id, "status": {"$in": ["success", "failed"]}, "duration": {"$ne": None}}
        ).limit(10))
        if completed_runs:
            durations = [run.get("duration", 0) for run in completed_runs if run.get("duration") is not None]
            if durations:
                avg_duration = sum(durations) / len(durations)
        
        # Get last failure reason
        last_failure_reason = None
        if failed_runs > 0:
            last_failed = db.job_runs.find_one(
                {"job_id": job_id, "status": "failed"},
                sort=[("start_ts", -1)]
            )
            if last_failed:
                last_failure_reason = last_failed.get("completion_reason")
        
        overview.append(
            {
                "job_id": job_id,
                "name": job.get("name", ""),
                "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
                "tags": job.get("tags", []),
                "total_runs": total_runs,
                "success_runs": success_runs,
                "failed_runs": failed_runs,
                "queued_runs": queued,
                "last_run": last_run_doc,
                "recent_runs": recent_runs,
                "avg_duration_seconds": avg_duration,
                "last_failure_reason": last_failure_reason,
            }
        )
    return overview


def _serialize_ts(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Support both "...Z" and offset-less iso timestamps.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


@router.get("/overview/queue")
def queue_overview(request: Request):
    db = get_db()
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    def _parse_limit(name: str, default: int = 100) -> int:
        raw = request.query_params.get(name)
        if raw is None:
            return default
        try:
            return max(1, min(int(raw), 500))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{name} must be an integer") from exc

    pending_limit = _parse_limit("pending_limit")
    upcoming_limit = _parse_limit("upcoming_limit")

    if is_admin and force_domain:
        query = {"domain": force_domain}
    elif is_admin:
        query = {}
    else:
        query = {"domain": domain}

    job_docs = list(db.job_definitions.find(query))
    jobs_by_id = {doc["_id"]: doc for doc in job_docs}

    pending: List[Dict[str, Any]] = []
    pending_domains: List[str]
    if is_admin and not force_domain:
        pending_domains = sorted({doc.get("domain", "prod") for doc in job_docs} | set(r.smembers("hydra:domains") or []))
    elif is_admin and force_domain:
        pending_domains = [force_domain]
    else:
        pending_domains = [domain]

    # Track total pending count per domain (before the page limit is applied).
    pending_total: Dict[str, int] = {}
    for pending_domain in pending_domains:
        pending_total[pending_domain] = int(r.zcard(f"job_queue:{pending_domain}:pending") or 0)
        items = r.zrange(f"job_queue:{pending_domain}:pending", 0, pending_limit - 1, withscores=True) or []
        for job_id, score in items:
            job = jobs_by_id.get(job_id)
            if not job and not is_admin:
                continue
            meta = r.hgetall(f"job_enqueue_meta:{pending_domain}:{job_id}") or {}
            enqueued_ts = meta.get("enqueued_ts")
            pending.append(
                {
                    "job_id": job_id,
                    "name": (job or {}).get("name", job_id),
                    "user": (job or {}).get("user", ""),
                    "domain": (job or {}).get("domain", pending_domain),
                    "priority": (job or {}).get("priority"),
                    "schedule_mode": ((job or {}).get("schedule") or {}).get("mode", "immediate"),
                    "next_run_at": _serialize_ts(((job or {}).get("schedule") or {}).get("next_run_at")),
                    "queue_score": score,
                    "enqueued_ts": (
                        _serialize_ts(datetime.fromtimestamp(float(enqueued_ts), tz=timezone.utc)) if enqueued_ts else None
                    ),
                    "reason": meta.get("reason"),
                    "no_worker_count": int(meta.get("no_worker_count", 0)),
                }
            )

    # Keep "closest to dispatch" first (lowest score), then oldest enqueue.
    pending.sort(key=lambda item: (item.get("queue_score", 0), item.get("enqueued_ts") or ""))
    pending = pending[:pending_limit]

    upcoming: List[Dict[str, Any]] = []
    for job in job_docs:
        schedule = job.get("schedule") or {}
        if not schedule.get("enabled", True):
            continue
        if schedule.get("mode") not in {"cron", "interval"}:
            continue
        next_run = schedule.get("next_run_at")
        next_run_dt = _coerce_datetime(next_run)
        if not next_run_dt:
            continue
        upcoming.append(
            {
                "job_id": job["_id"],
                "name": job.get("name", job["_id"]),
                "user": job.get("user", ""),
                "domain": job.get("domain", "prod"),
                "priority": job.get("priority"),
                "schedule_mode": schedule.get("mode", "immediate"),
                "next_run_at": _serialize_ts(next_run_dt),
            }
        )
    upcoming.sort(key=lambda item: item.get("next_run_at") or "")
    upcoming = upcoming[:upcoming_limit]

    return {"pending": pending, "upcoming": upcoming, "pending_total": pending_total}


@router.get("/overview/pressure")
def queue_pressure(request: Request):
    """Return per-domain backpressure indicators.

    Provides operational visibility into queue depth, starvation, and
    worker capacity so operators can detect and diagnose dispatch pressure
    without needing Redis access.

    Fields per domain:
    - ``pending_total``: total jobs in the pending queue.
    - ``stalled_jobs``: jobs with ``no_worker_count`` >= starvation threshold.
    - ``max_no_worker_count``: highest ``no_worker_count`` across all pending jobs.
    - ``worker_queue_depths``: per-worker depth of dispatched-but-not-started queues.
    - ``total_worker_queue_depth``: sum of all per-worker queue depths.
    - ``online_workers``: number of workers currently heartbeating.
    - ``total_running``: sum of ``current_running`` across online workers.
    - ``total_capacity``: sum of ``max_concurrency`` across online workers.
    """
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    starvation_threshold = int(os.getenv("SCHEDULER_STARVATION_WARN_THRESHOLD", "5"))
    ttl = max(2, int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10")))

    if is_admin and not force_domain:
        known_domains = sorted(set(r.smembers("hydra:domains") or []) | {"prod"})
    else:
        known_domains = [force_domain or domain]

    results: List[Dict[str, Any]] = []
    now = time.time()
    for dom in known_domains:
        # Pending backlog
        pending_total = int(r.zcard(f"job_queue:{dom}:pending") or 0)

        # Walk pending items to find stalled jobs (no_worker_count >= threshold)
        stalled_jobs: List[str] = []
        max_no_worker_count = 0
        if pending_total > 0:
            all_pending = r.zrange(f"job_queue:{dom}:pending", 0, -1) or []
            for job_id in all_pending:
                meta = r.hgetall(f"job_enqueue_meta:{dom}:{job_id}") or {}
                nwc = int(meta.get("no_worker_count", 0))
                if nwc > max_no_worker_count:
                    max_no_worker_count = nwc
                if nwc >= starvation_threshold:
                    stalled_jobs.append(job_id)

        # Per-worker queue depths (dispatched-but-not-started).
        # Keys match job_queue:<dom>:<worker_id>; skip the domain pending queue.
        worker_queue_depths: Dict[str, int] = {}
        expected_prefix = f"job_queue:{dom}:"
        for key in r.scan_iter(f"job_queue:{dom}:*"):
            if not key.startswith(expected_prefix):
                continue
            suffix = key[len(expected_prefix):]
            if not suffix or suffix == "pending":
                continue
            depth = int(r.llen(key) or 0)
            if depth > 0:
                worker_queue_depths[suffix] = depth
        total_worker_queue_depth = sum(worker_queue_depths.values())

        # Online worker capacity
        online_workers = 0
        total_running = 0
        total_capacity = 0
        expected_worker_prefix = f"workers:{dom}:"
        for wkey in r.scan_iter(f"workers:{dom}:*"):
            if not wkey.startswith(expected_worker_prefix):
                continue
            wid = wkey[len(expected_worker_prefix):]
            if not wid:
                continue
            hb = r.zscore(f"worker_heartbeats:{dom}", wid) or 0
            if (now - hb) > ttl:
                continue
            wdata = r.hgetall(wkey) or {}
            if (wdata.get("state") or "online") != "online":
                continue
            online_workers += 1
            total_running += int(wdata.get("current_running", 0))
            total_capacity += int(wdata.get("max_concurrency", 1))

        results.append(
            {
                "domain": dom,
                "pending_total": pending_total,
                "stalled_jobs": stalled_jobs,
                "stalled_count": len(stalled_jobs),
                "max_no_worker_count": max_no_worker_count,
                "starvation_threshold": starvation_threshold,
                "worker_queue_depths": worker_queue_depths,
                "total_worker_queue_depth": total_worker_queue_depth,
                "online_workers": online_workers,
                "total_running": total_running,
                "total_capacity": total_capacity,
            }
        )

    return {"domains": results}


def _build_dependency_graph(
    jobs_by_id: Dict[str, Dict[str, Any]],
    root_job_id: str,
) -> tuple[list[str], list[Dict[str, str]]]:
    if root_job_id not in jobs_by_id:
        return [], []

    children_by_id: Dict[str, set[str]] = {}
    for job_id, job in jobs_by_id.items():
        for dep_id in job.get("depends_on", []) or []:
            children_by_id.setdefault(dep_id, set()).add(job_id)

    included: set[str] = set()
    stack = [root_job_id]
    while stack:
        current = stack.pop()
        if current in included:
            continue
        included.add(current)
        # Only traverse parents that exist in this domain snapshot; missing refs are
        # represented later as placeholder nodes when edges are materialized.
        for parent in jobs_by_id.get(current, {}).get("depends_on", []) or []:
            if parent in jobs_by_id:
                stack.append(parent)
        for child in children_by_id.get(current, set()):
            if child in jobs_by_id:
                stack.append(child)

    edges: list[Dict[str, str]] = []
    missing_nodes: set[str] = set()
    for job_id in included:
        for dep_id in jobs_by_id.get(job_id, {}).get("depends_on", []) or []:
            edges.append({"source": dep_id, "target": job_id})
            if dep_id not in jobs_by_id:
                missing_nodes.add(dep_id)

    ordered_nodes = sorted(included | missing_nodes)
    return ordered_nodes, edges


@router.get("/jobs/{job_id}/grid")
def job_grid(job_id: str, request: Request):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and job.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    force_domain = request.query_params.get("domain")
    runs = _fetch_job_runs(job_id, domain_filter=None if (is_admin and not force_domain) else (force_domain or domain))
    task_id = "task_main"
    tasks = [
        {
            "task_id": task_id,
            "label": job.get("name", task_id),
            "instances": [
                {
                    "run_id": run["_id"],
                    "status": run.get("status"),
                    "start_ts": _serialize_ts(run.get("start_ts")),
                    "end_ts": _serialize_ts(run.get("end_ts")),
                    "duration": run.get("duration"),
                }
                for run in runs
            ],
        }
    ]
    run_summary = [
        {
            "run_id": run["_id"],
            "status": run.get("status"),
            "start_ts": _serialize_ts(run.get("start_ts")),
            "end_ts": _serialize_ts(run.get("end_ts")),
            "duration": run.get("duration"),
        }
        for run in runs
    ]
    return {"tasks": tasks, "runs": run_summary}


@router.get("/jobs/{job_id}/gantt")
def job_gantt(job_id: str, request: Request):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and job.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    force_domain = request.query_params.get("domain")
    runs = _fetch_job_runs(job_id, domain_filter=None if (is_admin and not force_domain) else (force_domain or domain))
    entries = [
        {
            "run_id": run["_id"],
            "start_ts": _serialize_ts(run.get("start_ts")),
            "end_ts": _serialize_ts(run.get("end_ts")),
            "duration": run.get("duration"),
            "status": run.get("status"),
        }
        for run in runs
    ]
    return {"entries": entries}


@router.get("/jobs/{job_id}/graph")
def job_graph(job_id: str, request: Request):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and job.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    force_domain = request.query_params.get("domain")
    graph_domain = (
        force_domain
        if (is_admin and force_domain)
        else job.get("domain", "prod")
    )
    jobs_in_domain = list(db.job_definitions.find({"domain": graph_domain}))
    jobs_by_id: Dict[str, Dict[str, Any]] = {str(doc["_id"]): doc for doc in jobs_in_domain}
    node_ids, edges = _build_dependency_graph(jobs_by_id, job_id)

    status_by_job: Dict[str, str] = {}
    if node_ids:
        latest_runs = db.job_runs.find(
            {"job_id": {"$in": node_ids}, "domain": graph_domain},
            {"job_id": 1, "status": 1, "start_ts": 1},
        ).sort("start_ts", -1)
        for run in latest_runs:
            run_job_id = run.get("job_id")
            if run_job_id and run_job_id not in status_by_job:
                status_by_job[run_job_id] = run.get("status", "unknown")

    nodes: list[Dict[str, Any]] = []
    for node_id in node_ids:
        node_job = jobs_by_id.get(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": (node_job or {}).get("name", f"{node_id} (missing)"),
                "status": status_by_job.get(node_id, "unknown"),
            }
        )
    return {"nodes": nodes, "edges": edges}


@router.get("/overview/statistics")
def jobs_statistics(request: Request):
    """Get aggregate statistics across all jobs"""
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    
    if is_admin and force_domain:
        query = {"domain": force_domain}
    elif is_admin:
        query = {}
    else:
        query = {"domain": domain}
    
    total_jobs = db.job_definitions.count_documents(query)
    
    # Count jobs by schedule mode
    cron_jobs = db.job_definitions.count_documents({**query, "schedule.mode": "cron"})
    interval_jobs = db.job_definitions.count_documents({**query, "schedule.mode": "interval"})
    immediate_jobs = db.job_definitions.count_documents({**query, "schedule.mode": "immediate"})
    
    # Count enabled vs disabled
    enabled_jobs = db.job_definitions.count_documents({**query, "schedule.enabled": True})
    disabled_jobs = total_jobs - enabled_jobs
    
    # Run statistics
    run_query = query.copy() if "domain" in query else {}
    if "domain" in run_query:
        run_query = {"domain": run_query["domain"]}
    
    total_runs = db.job_runs.count_documents(run_query)
    success_runs = db.job_runs.count_documents({**run_query, "status": "success"})
    failed_runs = db.job_runs.count_documents({**run_query, "status": "failed"})
    running_runs = db.job_runs.count_documents({**run_query, "status": "running"})
    
    # Get unique tags
    all_jobs = list(db.job_definitions.find(query, {"tags": 1}))
    all_tags = set()
    for job in all_jobs:
        all_tags.update(job.get("tags", []))
    
    return {
        "total_jobs": total_jobs,
        "schedule_breakdown": {
            "cron": cron_jobs,
            "interval": interval_jobs,
            "immediate": immediate_jobs,
        },
        "enabled_jobs": enabled_jobs,
        "disabled_jobs": disabled_jobs,
        "total_runs": total_runs,
        "success_runs": success_runs,
        "failed_runs": failed_runs,
        "running_runs": running_runs,
        "success_rate": (success_runs / total_runs * 100) if total_runs > 0 else 0,
        "available_tags": sorted(list(all_tags)),
    }
