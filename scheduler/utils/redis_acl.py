import hashlib
import secrets

from redis.exceptions import ResponseError

from ..redis_client import get_redis


def _normalized_domain(domain: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (domain or "").lower())
    cleaned = cleaned.strip("_") or "domain"
    return cleaned


def worker_acl_username(domain: str) -> str:
    return (domain or "").strip()


def _legacy_worker_acl_username(domain: str) -> str:
    normalized = _normalized_domain(domain)
    suffix = hashlib.sha1((domain or "").encode("utf-8")).hexdigest()[:8]
    return f"hydra_worker_{normalized}_{suffix}"


def worker_acl_key_patterns(domain: str) -> list[str]:
    return [
        f"~job_queue:{domain}:*",
        f"~workers:{domain}:*",
        f"~worker_heartbeats:{domain}",
        f"~worker_running_set:{domain}:*",
        f"~job_running:{domain}:*",
        f"~worker_metrics:{domain}:*",
        f"~log_stream:{domain}:*",
        f"~run_events:{domain}",
        f"~worker_ops:{domain}:*",
    ]


def worker_acl_channel_patterns(domain: str) -> list[str]:
    # Workers publish live log chunks on log_stream:<domain>:<run_id> (see
    # worker.py's stream_log()) and subscribe to job_kill:<domain> for
    # cancellation notifications — both need explicit channel ACL grants.
    return [f"&log_stream:{domain}:*", f"&job_kill:{domain}"]


def worker_acl_commands() -> list[str]:
    return [
        "+ping",
        "+exists",
        "+hexists",
        "+blpop",
        "+hset",
        "+hincrby",
        "+zadd",
        "+sadd",
        "+srem",
        "+rpush",
        "+ltrim",
        "+expire",
        "+del",
        "+publish",
        "+subscribe",
    ]


def ensure_worker_acl_user(domain: str, password: str | None = None) -> dict:
    r = get_redis()
    username = worker_acl_username(domain)
    legacy_username = _legacy_worker_acl_username(domain)
    generated_password = password or secrets.token_hex(24)
    args = [
        "ACL",
        "SETUSER",
        username,
        "reset",
        "on",
        f">{generated_password}",
    ]
    args.extend(worker_acl_key_patterns(domain))
    args.extend(worker_acl_channel_patterns(domain))
    args.extend(worker_acl_commands())
    r.execute_command(*args)
    # Remove any legacy hashed username for the same domain to avoid stale credential confusion.
    if legacy_username != username:
        try:
            r.execute_command("ACL", "DELUSER", legacy_username)
        except ResponseError:
            pass
    return {
        "username": username,
        "password": generated_password,
        "domain": domain,
        "keys": [k[1:] for k in worker_acl_key_patterns(domain)],
        "channels": [c[1:] for c in worker_acl_channel_patterns(domain)],
    }


def delete_worker_acl_user(domain: str) -> bool:
    r = get_redis()
    username = worker_acl_username(domain)
    legacy_username = _legacy_worker_acl_username(domain)
    removed_any = False
    try:
        removed = r.execute_command("ACL", "DELUSER", username)
        removed_any = removed_any or bool(int(removed))
    except ResponseError:
        pass
    if legacy_username != username:
        try:
            removed = r.execute_command("ACL", "DELUSER", legacy_username)
            removed_any = removed_any or bool(int(removed))
        except ResponseError:
            pass
    return removed_any
