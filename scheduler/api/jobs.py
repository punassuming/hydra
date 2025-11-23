from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

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


def _fetch_job_runs(job_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    runs = list(db.job_runs.find({"job_id": job_id}).sort("_id", 1))
    normalized: List[Dict[str, Any]] = []
    for run in runs:
        doc = dict(run)
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        stdout = (doc.get("stdout") or "")[:]
        stderr = (doc.get("stderr") or "")[:]
        doc["stdout_tail"] = stdout[-4096:]
        doc["stderr_tail"] = stderr[-4096:]
        duration = None
        if doc.get("start_ts") and doc.get("end_ts"):
            try:
                duration = (doc["end_ts"] - doc["start_ts"]).total_seconds()
            except Exception:
                duration = None
        doc["duration"] = duration
        normalized.append(doc)
    return normalized


def _enqueue_job(job_id: str, reason: str, extra_payload: dict | None = None):
    r = get_redis()
    r.rpush("job_queue:pending", job_id)
    payload = {"job_id": job_id, "reason": reason}
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
def list_jobs():
    db = get_db()
    docs = list(db.job_definitions.find({}).sort("created_at", -1))
    return [JobDefinition.model_validate(doc) for doc in docs]


@router.post("/jobs/", response_model=JobDefinition)
def submit_job(job: JobCreate):
    db = get_db()
    job_def = JobDefinition(**job.model_dump())
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    if job_def.schedule.mode == "immediate":
        _enqueue_job(job_def.id, reason="immediate_submit")
    event_bus.publish(
        "job_submitted",
        {
            "job_id": job_def.id,
            "name": job_def.name,
            "user": job_def.user,
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
def get_job(job_id: str):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    return JobDefinition.model_validate(doc)


@router.get("/jobs/{job_id}/runs", response_model=List[JobRun])
def get_job_runs(job_id: str):
    runs = _fetch_job_runs(job_id)
    return [JobRun.model_validate(r) for r in runs]


@router.put("/jobs/{job_id}", response_model=JobDefinition)
def update_job(job_id: str, updates: JobUpdate):
    db = get_db()
    existing = db.job_definitions.find_one({"_id": job_id})
    if not existing:
        raise HTTPException(status_code=404, detail="job not found")
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
    event_bus.publish("job_updated", {"job_id": job_id})
    return job_def


@router.post("/jobs/{job_id}/validate", response_model=JobValidationResult)
def validate_job(job_id: str):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    job_def = JobDefinition.model_validate(doc)
    return _validate_job_definition(job_def)


@router.post("/jobs/validate", response_model=JobValidationResult)
def validate_payload(job: JobCreate):
    job_def = JobDefinition(**job.model_dump())
    return _validate_job_definition(job_def)


@router.post("/jobs/{job_id}/run")
def run_job_now(job_id: str):
    db = get_db()
    doc = db.job_definitions.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="job not found")
    _enqueue_job(job_id, reason="manual_run")
    return {"job_id": job_id, "queued": True}


@router.post("/jobs/adhoc", response_model=JobDefinition)
def run_adhoc_job(job: JobCreate):
    db = get_db()
    adhoc_schedule = ScheduleConfig(mode="immediate", enabled=False)
    job_dict = job.model_dump()
    job_dict["schedule"] = adhoc_schedule.model_dump()
    job_def = JobDefinition(**job_dict)
    validation = _validate_job_definition(job_def)
    if not validation.valid:
        raise HTTPException(status_code=422, detail=validation.errors)
    job_def = _attach_schedule(job_def, force=True)
    db.job_definitions.insert_one(job_def.to_mongo())
    _enqueue_job(job_def.id, reason="adhoc_run")
    return job_def


@router.get("/overview/jobs")
def jobs_overview():
    db = get_db()
    job_docs = list(db.job_definitions.find({}))
    print(f"Job Docs: {job_docs}")
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
        last_run = db.job_runs.find({"job_id": job_id}).sort("start_ts", -1).limit(1)
        last_run_doc = next(iter(last_run), None)
        if last_run_doc and "_id" in last_run_doc:
            last_run_doc["_id"] = str(last_run_doc["_id"])
            logs_out = last_run_doc.get("stdout") or ""
            logs_err = last_run_doc.get("stderr") or ""
            last_run_doc["stdout_tail"] = logs_out[-4096:]
            last_run_doc["stderr_tail"] = logs_err[-4096:]
        overview.append(
            {
                "job_id": job_id,
                "name": job.get("name", ""),
                "schedule_mode": (job.get("schedule") or {}).get("mode", "immediate"),
                "total_runs": total_runs,
                "success_runs": success_runs,
                "failed_runs": failed_runs,
                "last_run": last_run_doc,
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
