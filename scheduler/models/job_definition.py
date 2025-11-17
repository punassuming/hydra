from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
import uuid

from .executor import ExecutorConfig, ShellExecutor


class Affinity(BaseModel):
    os: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    allowed_users: List[str] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    mode: Literal["immediate", "cron", "interval"] = "immediate"
    cron: Optional[str] = None
    interval_seconds: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    timezone: str = "UTC"
    enabled: bool = True


class CompletionCriteria(BaseModel):
    exit_codes: List[int] = Field(default_factory=lambda: [0])
    stdout_contains: List[str] = Field(default_factory=list)
    stdout_not_contains: List[str] = Field(default_factory=list)
    stderr_contains: List[str] = Field(default_factory=list)
    stderr_not_contains: List[str] = Field(default_factory=list)


class JobDefinition(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, alias="_id")
    name: str
    user: str = "default"
    affinity: Affinity
    executor: ExecutorConfig = Field(default_factory=lambda: ShellExecutor(script=""))
    retries: int = 0
    timeout: int = 0
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    completion: CompletionCriteria = Field(default_factory=CompletionCriteria)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True

    def to_mongo(self) -> dict:
        d = self.model_dump(by_alias=True)
        d["created_at"] = self.created_at
        d["updated_at"] = self.updated_at
        return d


class JobCreate(BaseModel):
    name: str
    user: str = "default"
    affinity: Affinity
    executor: ExecutorConfig = Field(default_factory=lambda: ShellExecutor(script=""))
    retries: int = 0
    timeout: int = 0
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    completion: CompletionCriteria = Field(default_factory=CompletionCriteria)


class JobUpdate(BaseModel):
    name: Optional[str] = None
    user: Optional[str] = None
    affinity: Optional[Affinity] = None
    executor: Optional[ExecutorConfig] = None
    retries: Optional[int] = None
    timeout: Optional[int] = None
    schedule: Optional[ScheduleConfig] = None
    completion: Optional[CompletionCriteria] = None


class JobValidationResult(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    next_run_at: Optional[datetime] = None
