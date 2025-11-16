from datetime import datetime
from typing import List

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
                errors.append(f"python code syntax error: {exc.msg} (line {exc.lineno})")
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
    needs_init = force or (schedule.mode != "immediate" and schedule.enabled and schedule.next_run_at is None)
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
            "next_run_at": job_def.schedule.next_run_at.isoformat() if job_def.schedule.next_run_at else None,
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
    db = get_db()
    runs = list(db.job_runs.find({"job_id": job_id}).sort("_id", 1))
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
