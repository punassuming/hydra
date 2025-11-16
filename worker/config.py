import os
import platform
from typing import List


def get_worker_id() -> str:
    return os.getenv("WORKER_ID", f"worker-{platform.node()}-{os.getpid()}")


def get_tags() -> List[str]:
    tags = os.getenv("WORKER_TAGS", "")
    return [t.strip() for t in tags.split(",") if t.strip()]


def get_allowed_users() -> List[str]:
    v = os.getenv("ALLOWED_USERS", "")
    return [t.strip() for t in v.split(",") if t.strip()]


def get_max_concurrency() -> int:
    try:
        return max(int(os.getenv("MAX_CONCURRENCY", "2")), 1)
    except Exception:
        return 2

