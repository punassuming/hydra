from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Request

from ..mongo_client import get_db
from ..redis_client import get_redis
from ..models.job_definition import (
    JobCreate,
    JobDefinition,
    JobUpdate,
    JobValidationResult,
    ScheduleConfig,
)
from ..models.job_run import JobRun
from ..event_bus import event_bus
from ..utils.schedule import initialize_schedule


router = APIRouter()


def _fetch_job_runs(job_id: str, domain_filter: str | None = None) -> List[Dict[str, Any]]:
    db = get_db()
    query: Dict[str, Any] = {"job_id": job_id}
    if domain_filter:
        query["domain"] = domain_filter
    runs = list(db.job_runs.find(query).sort("_id", 1))
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


def _enqueue_job(job_id: str, reason: str, extra_payload: dict | None = None, priority: int | None = None, domain: str = "prod"):
    r = get_redis()
    score = float(priority if priority is not None else 5)
    r.sadd("hydra:domains", domain)
    r.zadd(f"job_queue:{domain}:pending", {job_id: score})
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
    elif exec_type in {"shell", "batch"}:
        script = getattr(executor, "script", "")
        if not script.strip():
            errors.append(f"{exec_type} executor requires non-empty script")
    elif exec_type == "external":
        command = getattr(executor, "command", "")
        if not command.strip():
            errors.append("external executor requires a command or binary path")
    else:
        errors.append("executor.type must be one of python|shell|batch|external")

    try:
        next_run_at = initialize_schedule(job.schedule, datetime.utcnow()).next_run_at
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
        new_schedule = initialize_schedule(schedule, datetime.utcnow())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=[str(exc)])
    return job_def.copy(update={"schedule": new_schedule})


@router.get("/jobs/", response_model=List[JobDefinition])
def list_jobs(request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    query = {} if is_admin else {"domain": domain}
    docs = list(db.job_definitions.find(query).sort("created_at", -1))
    return [JobDefinition.model_validate(doc) for doc in docs]


@router.post("/jobs/", response_model=JobDefinition)
def submit_job(job: JobCreate, request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    job_def = JobDefinition(**job.model_dump(), domain=domain)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    if job_def.schedule.mode == "immediate":
        _enqueue_job(job_def.id, reason="immediate_submit", priority=job_def.priority)
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
    return job_def


@router.get("/jobs/{job_id}", response_model=JobDefinition)
def get_job(job_id: str, request: Request):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    return JobDefinition.model_validate(doc)


@router.get("/jobs/{job_id}/runs", response_model=List[JobRun])
def get_job_runs(job_id: str, request: Request):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and job.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    runs = _fetch_job_runs(job_id, domain_filter=None if is_admin else domain)
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
    merged["updated_at"] = datetime.utcnow()
    job_def = JobDefinition.model_validate(merged)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force="schedule" in update_doc)
    db.job_definitions.replace_one({"_id": job_id}, job_def.to_mongo())
    event_bus.publish("job_updated", {"job_id": job_id, "domain": job_def.domain})
    return job_def


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
    job_def = JobDefinition(**job.model_dump(), domain=domain)
    return _validate_job_definition(job_def)


@router.post("/jobs/{job_id}/run")
def run_job_now(job_id: str, request: Request):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and doc.get("domain", "prod") != domain:
        raise HTTPException(status_code=403, detail="forbidden")
    priority = doc.get("priority", 5)
    _enqueue_job(job_id, reason="manual_run", priority=priority, domain=doc.get("domain", "prod"))
    event_bus.publish("job_manual_run", {"job_id": job_id, "domain": doc.get("domain", "prod")})
    return {"job_id": job_id, "queued": True}


@router.post("/jobs/adhoc", response_model=JobDefinition)
def run_adhoc_job(job: JobCreate, request: Request):
    db = get_db()
    domain = getattr(request.state, "domain", "prod")
    adhoc_schedule = ScheduleConfig(mode="immediate", enabled=False)
    job_dict = job.model_dump()
    job_dict["schedule"] = adhoc_schedule.model_dump()
    job_def = JobDefinition(**job_dict, domain=domain)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    _enqueue_job(job_def.id, reason="adhoc_run", priority=job_def.priority, domain=domain)
    return job_def


@router.get("/overview/jobs")
def jobs_overview(request: Request):
    db = get_db()
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    query = {} if is_admin else {"domain": domain}
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
        overview.append(
            {
                "job_id": job_id,
                "name": job.get("name", ""),
                "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
                "total_runs": total_runs,
                "success_runs": success_runs,
                "failed_runs": failed_runs,
                "queued_runs": queued,
                "last_run": last_run_doc,
                "recent_runs": recent_runs,
            }
        )
    return overview


def _serialize_ts(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@router.get("/jobs/{job_id}/grid")
def job_grid(job_id: str):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    runs = _fetch_job_runs(job_id)
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
def job_gantt(job_id: str):
    db = get_db()
    if not db.job_definitions.find_one({"_id": job_id}):
        raise HTTPException(status_code=404, detail="job not found")
    runs = _fetch_job_runs(job_id)
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
def job_graph(job_id: str):
    db = get_db()
    job = db.job_definitions.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    runs = _fetch_job_runs(job_id)
    last_status = runs[-1]["status"] if runs else "unknown"
    nodes = [
        {
            "id": job_id,
            "label": job.get("name", job_id),
            "status": last_status,
        }
    ]
    edges: List[Dict[str, Any]] = []
    return {"nodes": nodes, "edges": edges}
