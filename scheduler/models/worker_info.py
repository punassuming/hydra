from typing import List, Optional
from pydantic import BaseModel


class WorkerInfo(BaseModel):
    worker_id: str
    os: str
    tags: List[str]
    allowed_users: List[str]
    max_concurrency: int
    current_running: int
    last_heartbeat: Optional[float] = None
    status: str = "online"

