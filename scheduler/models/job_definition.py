from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid

from .executor import ExecutorConfig, ShellExecutor


class Affinity(BaseModel):
    os: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    allowed_users: List[str] = Field(default_factory=list)


class JobDefinition(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, alias="_id")
    name: str
    user: str
    affinity: Affinity
    executor: ExecutorConfig = Field(default_factory=lambda: ShellExecutor(script=""))
    retries: int = 0
    timeout: int = 0
    schedule: Optional[str] = None
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
    user: str
    affinity: Affinity
    executor: ExecutorConfig = Field(default_factory=lambda: ShellExecutor(script=""))
    retries: int = 0
    timeout: int = 0
    schedule: Optional[str] = None


class JobUpdate(BaseModel):
    name: Optional[str] = None
    user: Optional[str] = None
    affinity: Optional[Affinity] = None
    executor: Optional[ExecutorConfig] = None
    retries: Optional[int] = None
    timeout: Optional[int] = None
    schedule: Optional[str] = None


class JobValidationResult(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
