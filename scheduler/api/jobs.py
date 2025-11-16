from datetime import datetime
import uuid
from fastapi import APIRouter, HTTPException
from typing import Any, List

from ..mongo_client import get_db
from ..redis_client import get_redis
from ..models.job_definition import JobCreate, JobDefinition
from ..models.job_run import JobRun


router = APIRouter()


@router.post("/jobs/", response_model=JobDefinition)
def submit_job(job: JobCreate):
    db = get_db()
    r = get_redis()
    # Create job definition
    job_def = JobDefinition(**job.model_dump())
    db.job_definitions.insert_one(job_def.to_mongo())
    # Enqueue for scheduling
    r.rpush("job_queue:pending", job_def.id)
    # Seed an initial run record as pending so history exists
    run = JobRun(
        job_id=job_def.id,
        user=job_def.user,
        status="pending",
        start_ts=None,
        end_ts=None,
    ).model_dump(by_alias=True)
    db.job_runs.insert_one(run)
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

