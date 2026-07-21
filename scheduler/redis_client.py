import os

import redis
from redis.sentinel import Sentinel

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


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        sentinel_nodes = _parse_sentinel_nodes(os.getenv("REDIS_SENTINELS", ""))
        sentinel_master = (os.getenv("REDIS_SENTINEL_MASTER", "") or "").strip()

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
            redis_username = os.getenv("REDIS_USERNAME")
            redis_password = os.getenv("REDIS_PASSWORD")
            if redis_username:
                master_kwargs["username"] = redis_username
            if redis_password:
                master_kwargs["password"] = redis_password

            _redis_client = sentinel.master_for(sentinel_master, **master_kwargs)
        else:
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            kwargs = {"decode_responses": True}
            redis_username = os.getenv("REDIS_USERNAME")
            redis_password = os.getenv("REDIS_PASSWORD")
            if redis_username:
                kwargs["username"] = redis_username
            if redis_password:
                kwargs["password"] = redis_password
            _redis_client = redis.from_url(url, **kwargs)
    return _redis_client
