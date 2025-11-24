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


def get_initial_state() -> str:
    state = os.getenv("WORKER_STATE", "online").lower()
    return state if state in {"online", "draining", "disabled"} else "online"


def get_domain() -> str:
    return os.getenv("WORKER_DOMAIN", "prod")


def get_domain_token() -> str:
    token = os.getenv("WORKER_DOMAIN_TOKEN", "") or os.getenv("API_TOKEN", "")
    if not token:
        raise RuntimeError("WORKER_DOMAIN_TOKEN (or API_TOKEN) is required for domain-scoped worker registration")
    return token


def get_queues() -> List[str]:
    v = os.getenv("WORKER_QUEUES", "default")
    return [t.strip() for t in v.split(",") if t.strip()]
