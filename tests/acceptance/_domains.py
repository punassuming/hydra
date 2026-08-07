"""Domain provisioning helpers — thin wrappers around the same admin API
calls scripts/start-domain-workers.sh uses, so the acceptance suite doesn't
need shell/stdout-scraping to get a freshly rotated token + Redis ACL
password back as native Python values.
"""

import secrets
from dataclasses import dataclass, field
from typing import List

from ._client import ApiError, Client


@dataclass
class DomainHandle:
    name: str
    token: str
    redis_username: str
    redis_password: str
    client: Client
    worker_names: List[str] = field(default_factory=list)  # populated by whoever launches workers


def random_domain_name(prefix: str = "accept") -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def create_domain(admin: Client, name: str) -> DomainHandle:
    resp = admin.post("/admin/domains", {"domain": name, "display_name": f"Acceptance: {name}"})
    acl = resp["worker_redis_acl"]
    return DomainHandle(
        name=name,
        token=resp["token"],
        redis_username=acl["username"],
        redis_password=acl["password"],
        client=Client(admin.base_url, resp["token"], domain=name),
    )


def delete_domain(admin: Client, name: str) -> None:
    try:
        admin.delete(f"/admin/domains/{name}")
    except ApiError:
        pass  # already gone, or never fully created — fine for cleanup


def wait_for_worker_online(client: Client, timeout: float = 30.0, poll_interval: float = 1.0) -> List[dict]:
    from ._infra import wait_until

    result: List[dict] = []

    def _check() -> bool:
        workers = client.get("/workers/") or []
        online = [w for w in workers if w.get("connectivity_status") == "online"]
        if online:
            result.extend(online)
            return True
        return False

    wait_until(_check, timeout=timeout, interval=poll_interval, description="a worker to come online")
    return result
