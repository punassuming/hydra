from typing import List, Optional
from pydantic import BaseModel


class WorkerInfo(BaseModel):
    worker_id: str
    domain: str = "prod"
    os: str
    tags: List[str]
    allowed_users: List[str]
    max_concurrency: int
    current_running: int
    last_heartbeat: Optional[float] = None
    status: str = "online"
    state: str = "online"
    cpu_count: Optional[int] = None
    python_version: Optional[str] = None
    cwd: Optional[str] = None
    hostname: Optional[str] = None
    ip: Optional[str] = None
    subnet: Optional[str] = None
    deployment_type: Optional[str] = None
    run_user: Optional[str] = None
    running_jobs: List[str] = []
