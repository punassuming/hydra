from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class JobRun(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    job_id: str
    user: str
    worker_id: Optional[str] = None
    start_ts: Optional[datetime] = None
    scheduled_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    status: str = "pending"  # pending | running | success | failed
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    slot: Optional[int] = None
    attempt: Optional[int] = None
    retries_remaining: Optional[int] = None
    schedule_tick: Optional[str] = None
    executor_type: Optional[str] = None
    queue_latency_ms: Optional[float] = None

    class Config:
        populate_by_name = True
