import os
from urllib.parse import urlparse

import redis
from redis.sentinel import Sentinel

from .config import get_domain

_redis_client = None


def _parse_sentinel_nodes(raw: str) -> list[tuple[str, int]]:
    nodes: list[tuple[str, int]] = []
    for entry in (raw or "").split(","):
        part = entry.strip()
        if not part:
            continue
        if ":" in part:
            host, port_str = part.rsplit(":", 1)
            try:
                nodes.append((host.strip(), int(port_str)))
            except ValueError:
                continue
        else:
            nodes.append((part, 26379))
    return nodes


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in {"", "0", "false", "no", "off"}


def _url_has_credentials(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return bool(parsed.username and parsed.password)


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        sentinel_nodes = _parse_sentinel_nodes(os.getenv("REDIS_SENTINELS", ""))
        sentinel_master = (os.getenv("REDIS_SENTINEL_MASTER", "") or "").strip()
        require_acl = _truthy(os.getenv("WORKER_REQUIRE_REDIS_ACL", "true"))

        if sentinel_nodes and sentinel_master:
            redis_db = int(os.getenv("REDIS_DB", "0"))
            socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))
            sentinel_kwargs = {}
            sentinel_username = os.getenv("REDIS_SENTINEL_USERNAME")
            sentinel_password = os.getenv("REDIS_SENTINEL_PASSWORD")
            if sentinel_username:
                sentinel_kwargs["username"] = sentinel_username
            if sentinel_password:
                sentinel_kwargs["password"] = sentinel_password

            sentinel = Sentinel(
                sentinel_nodes,
                socket_timeout=socket_timeout,
                sentinel_kwargs=sentinel_kwargs or None,
            )

            master_kwargs = {
                "db": redis_db,
                "decode_responses": True,
                "socket_timeout": socket_timeout,
            }
            redis_username = get_domain() if require_acl else os.getenv("REDIS_USERNAME")
            redis_password = os.getenv("REDIS_PASSWORD")
            if require_acl and not (redis_username and redis_password):
                raise RuntimeError("WORKER_REQUIRE_REDIS_ACL=true requires REDIS_PASSWORD with DOMAIN when using Sentinel")
            if redis_username:
                master_kwargs["username"] = redis_username
            if redis_password:
                master_kwargs["password"] = redis_password

            _redis_client = sentinel.master_for(sentinel_master, **master_kwargs)
        else:
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            redis_username = get_domain() if require_acl else os.getenv("REDIS_USERNAME")
            redis_password = os.getenv("REDIS_PASSWORD")
            if require_acl and not ((redis_username and redis_password) or _url_has_credentials(url)):
                raise RuntimeError(
                    "WORKER_REQUIRE_REDIS_ACL=true requires REDIS_PASSWORD with DOMAIN, or REDIS_URL with embedded credentials"
                )
            kwargs = {"decode_responses": True}
            if redis_username:
                kwargs["username"] = redis_username
            if redis_password:
                kwargs["password"] = redis_password
            _redis_client = redis.from_url(url, **kwargs)
    return _redis_client
