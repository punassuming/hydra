import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..models.worker_info import WorkerInfo
from ..mongo_client import get_db
from ..redis_client import get_redis
from ..utils.auth import get_domain_token_hash
from ..utils.worker_ops import append_worker_op

router = APIRouter()


class WorkerStatePayload(BaseModel):
    state: str


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _load_metrics_history(r, domain: str, worker_id: str, max_points: int = 720) -> list[dict]:
    history_key = f"worker_metrics:{domain}:{worker_id}:history"
    raw_points = r.lrange(history_key, -max_points, -1) or []
    samples = []
    for raw in raw_points:
        try:
            samples.append(json.loads(raw))
        except Exception:
            continue
    return samples


def _normalize_state(value: str | None) -> str:
    normalized = (value or "online").strip().lower()
    if normalized == "disabled":
        return "offline"
    if normalized not in {"online", "draining", "offline"}:
        return "online"
    return normalized


def _heartbeat_connectivity(heartbeat_ts: float | None, ttl_seconds: int) -> tuple[str, float | None]:
    if heartbeat_ts is None:
        return "offline", None
    age = max(0.0, time.time() - float(heartbeat_ts))
    return ("online" if age <= ttl_seconds else "offline"), age


def _metrics_summary(r, domain: str, worker_id: str, data: dict) -> dict:
    """
    Return current + rolling 30m maxima from Redis history maintained by worker heartbeat.
    """
    samples = _load_metrics_history(r, domain, worker_id, max_points=240)

    if not samples:
        memory_rss_mb = _to_float(data.get("memory_rss_mb"))
        process_count = _to_int(data.get("process_count"))
        load_1m = _to_float(data.get("load_1m"))
        load_5m = _to_float(data.get("load_5m"))
        metrics_ts = _to_float(data.get("metrics_ts"))
        return {
            "memory_rss_mb": memory_rss_mb,
            "process_count": process_count,
            "load_1m": load_1m,
            "load_5m": load_5m,
            "memory_rss_mb_max_30m": memory_rss_mb,
            "process_count_max_30m": process_count,
            "load_1m_max_30m": load_1m,
            "metrics_updated_at": metrics_ts,
        }

    latest = samples[-1]
    mem_values = [
        float(s.get("memory_rss_mb"))
        for s in samples
        if s.get("memory_rss_mb") is not None
    ]
    proc_values = [
        int(s.get("process_count"))
        for s in samples
        if s.get("process_count") is not None
    ]
    load_values = [
        float(s.get("load_1m"))
        for s in samples
        if s.get("load_1m") is not None
    ]
    return {
        "memory_rss_mb": float(latest.get("memory_rss_mb")) if latest.get("memory_rss_mb") is not None else None,
        "process_count": int(latest.get("process_count")) if latest.get("process_count") is not None else None,
        "load_1m": float(latest.get("load_1m")) if latest.get("load_1m") is not None else None,
        "load_5m": float(latest.get("load_5m")) if latest.get("load_5m") is not None else None,
        "memory_rss_mb_max_30m": max(mem_values) if mem_values else None,
        "process_count_max_30m": max(proc_values) if proc_values else None,
        "load_1m_max_30m": max(load_values) if load_values else None,
        "metrics_updated_at": float(latest.get("ts")) if latest.get("ts") is not None else None,
    }


def _resolve_worker_key(request: Request, worker_id: str) -> tuple[str, str, dict]:
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")

    if not is_admin:
        key = f"workers:{domain}:{worker_id}"
        if not r.exists(key):
            raise HTTPException(status_code=404, detail="worker not found")
        return domain, key, r.hgetall(key)

    if force_domain:
        key = f"workers:{force_domain}:{worker_id}"
        if not r.exists(key):
            raise HTTPException(status_code=404, detail="worker not found")
        return force_domain, key, r.hgetall(key)

    for key in r.scan_iter(f"workers:*:{worker_id}"):
        data = r.hgetall(key)
        parts = key.split(":")
        dom = parts[1] if len(parts) >= 3 else domain
        return dom, key, data
    raise HTTPException(status_code=404, detail="worker not found")


def _truthy_flag(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _requeue_worker_queue(r, domain: str, worker_id: str) -> int:
    """
    Move any queued envelopes from worker-specific queue back to domain pending queue.
    """
    queue_key = f"job_queue:{domain}:{worker_id}"
    items = r.lrange(queue_key, 0, -1) or []
    if not items:
        return 0
    requeued = 0
    for raw in items:
        try:
            envelope = json.loads(raw)
        except Exception:
            continue
        job_id = envelope.get("job_id")
        priority = float((envelope.get("job") or {}).get("priority", 5))
        if not job_id:
            continue
        r.zadd(f"job_queue:{domain}:pending", {job_id: priority})
        r.hset(
            f"job_enqueue_meta:{domain}:{job_id}",
            mapping={
                "enqueued_ts": envelope.get("enqueued_ts") or time.time(),
                "reason": "worker_detached",
                "retry_attempt": envelope.get("retry_attempt", 0),
            },
        )
        r.expire(f"job_enqueue_meta:{domain}:{job_id}", 24 * 3600)
        requeued += 1
    r.delete(queue_key)
    return requeued


@router.get("/workers/", response_model=List[WorkerInfo])
def list_workers(request: Request):
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    force_domain = request.query_params.get("domain")
    ttl = max(2, int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10")))
    workers = []
    if is_admin and not force_domain:
        domains = [key.split(":")[1] for key in r.scan_iter("workers:*") if key.count(":") >= 2]
    else:
        domains = [force_domain or domain]
    domains = list(set(domains))
    if not domains:
        domains = [domain]
    for dom in domains:
        for key in r.scan_iter(f"workers:{dom}:*"):
            parts = key.split(":")
            wid = parts[2] if len(parts) > 2 else parts[-1]
            data = r.hgetall(key)
            expected_hash = get_domain_token_hash(dom)
            worker_hash = data.get("domain_token_hash")
            if expected_hash and worker_hash and worker_hash != expected_hash:
                continue
            metrics = _metrics_summary(r, dom, wid, data)
            hb = r.zscore(f"worker_heartbeats:{dom}", wid)
            connectivity_status, hb_age = _heartbeat_connectivity(hb, ttl)
            desired_state = _normalize_state(data.get("state", "online"))
            dispatch_status = "offline" if connectivity_status == "offline" else desired_state
            running_jobs = list(r.smembers(f"worker_running_set:{dom}:{wid}") or [])
            running_users_set = set()
            for job_id in running_jobs:
                user = r.hget(f"job_running:{dom}:{job_id}", "user")
                if user:
                    running_users_set.add(user)
            running_users = sorted(running_users_set)
            workers.append(
                WorkerInfo(
                    worker_id=wid,
                    domain=dom,
                    os=data.get("os", ""),
                    tags=(data.get("tags", "") or "").split(",") if data.get("tags") else [],
                    allowed_users=(data.get("allowed_users", "") or "").split(",") if data.get("allowed_users") else [],
                    max_concurrency=int(data.get("max_concurrency", 1)),
                    current_running=int(data.get("current_running", 0)),
                    last_heartbeat=hb,
                    status=connectivity_status,
                    state=desired_state,
                    cpu_count=int(data.get("cpu_count", 0)) or None,
                    python_version=data.get("python_version"),
                    cwd=data.get("cwd"),
                    hostname=data.get("hostname"),
                    ip=data.get("ip"),
                    subnet=data.get("subnet"),
                    deployment_type=data.get("deployment_type"),
                    run_user=data.get("run_user"),
                    shells=(data.get("shells", "") or "").split(",") if data.get("shells") else [],
                    capabilities=(data.get("capabilities", "") or "").split(",") if data.get("capabilities") else [],
                    process_count=metrics["process_count"],
                    memory_rss_mb=metrics["memory_rss_mb"],
                    load_1m=metrics["load_1m"],
                    load_5m=metrics["load_5m"],
                    process_count_max_30m=metrics["process_count_max_30m"],
                    memory_rss_mb_max_30m=metrics["memory_rss_mb_max_30m"],
                    load_1m_max_30m=metrics["load_1m_max_30m"],
                    metrics_updated_at=metrics["metrics_updated_at"],
                    running_jobs=running_jobs,
                    running_users=running_users,
                    connectivity_status=connectivity_status,
                    dispatch_status=dispatch_status,
                    heartbeat_age_seconds=hb_age,
                )
            )
    return workers


@router.get("/workers/{worker_id}/metrics")
def worker_metrics(worker_id: str, request: Request):
    r = get_redis()
    domain, _key, data = _resolve_worker_key(request, worker_id)
    minutes = max(5, min(int(request.query_params.get("minutes", "30")), 240))
    cutoff_ts = time.time() - (minutes * 60)

    samples = _load_metrics_history(r, domain, worker_id, max_points=2000)
    points = []
    for sample in samples:
        ts = _to_float(sample.get("ts"))
        if ts is None or ts < cutoff_ts:
            continue
        points.append(
            {
                "ts": ts,
                "memory_rss_mb": _to_float(sample.get("memory_rss_mb")),
                "process_count": _to_int(sample.get("process_count")),
                "load_1m": _to_float(sample.get("load_1m")),
                "load_5m": _to_float(sample.get("load_5m")),
            }
        )

    if not points:
        points = [
            {
                "ts": _to_float(data.get("metrics_ts")) or time.time(),
                "memory_rss_mb": _to_float(data.get("memory_rss_mb")),
                "process_count": _to_int(data.get("process_count")),
                "load_1m": _to_float(data.get("load_1m")),
                "load_5m": _to_float(data.get("load_5m")),
            }
        ]

    return {
        "worker_id": worker_id,
        "domain": domain,
        "window_minutes": minutes,
        "points": points,
    }


@router.get("/workers/{worker_id}/timeline")
def worker_timeline(worker_id: str, request: Request):
    db = get_db()
    domain, _key, data = _resolve_worker_key(request, worker_id)
    minutes = max(5, min(int(request.query_params.get("minutes", "180")), 1440))
    limit = max(50, min(int(request.query_params.get("limit", "800")), 2000))
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    runs = list(
        db.job_runs.find(
            {"domain": domain, "worker_id": worker_id, "start_ts": {"$gte": since}},
            {"job_id": 1, "start_ts": 1, "end_ts": 1, "status": 1, "slot": 1, "bypass_concurrency": 1},
        )
        .sort("start_ts", 1)
        .limit(limit)
    )
    job_ids = sorted({doc.get("job_id") for doc in runs if doc.get("job_id")})
    job_name_map = {
        doc.get("_id"): doc.get("name", doc.get("_id", ""))
        for doc in db.job_definitions.find({"_id": {"$in": job_ids}}, {"_id": 1, "name": 1})
    }

    now = datetime.now(timezone.utc)
    entries = []
    for doc in runs:
        start_ts = doc.get("start_ts")
        if not start_ts:
            continue
        end_ts = doc.get("end_ts") or now
        entries.append(
            {
                "run_id": str(doc.get("_id")),
                "job_id": doc.get("job_id"),
                "job_name": job_name_map.get(doc.get("job_id"), doc.get("job_id")),
                "status": doc.get("status", "running"),
                "start_ts": start_ts.timestamp(),
                "end_ts": end_ts.timestamp(),
                "slot": _to_int(doc.get("slot")) or 0,
                "bypass_concurrency": bool(doc.get("bypass_concurrency", False)),
            }
        )

    return {
        "worker_id": worker_id,
        "domain": domain,
        "window_minutes": minutes,
        "window_start_ts": since.timestamp(),
        "window_end_ts": now.timestamp(),
        "max_concurrency": int(data.get("max_concurrency", 1)),
        "entries": entries,
    }


@router.post("/workers/{worker_id}/state")
def set_worker_state(worker_id: str, payload: WorkerStatePayload, request: Request):
    """
    Set worker state to online|draining|offline.
    Draining/offline will prevent new dispatches; running jobs continue.
    """
    raw_state = payload.state.lower()
    if raw_state not in {"online", "draining", "offline", "disabled"}:
        return {"ok": False, "error": "invalid state"}
    state = _normalize_state(raw_state)
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    is_admin = getattr(request.state, "is_admin", False)
    key = f"workers:{domain}:{worker_id}"
    if not r.exists(key):
        if not is_admin:
            return {"ok": False, "error": "worker not found"}
        # allow admin to target any domain via query param ?domain=
        alt_domain = request.query_params.get("domain")
        if alt_domain and r.exists(f"workers:{alt_domain}:{worker_id}"):
            domain = alt_domain
            key = f"workers:{domain}:{worker_id}"
        else:
            return {"ok": False, "error": "worker not found"}
    previous_state = _normalize_state(r.hget(key, "state") or "online")
    r.hset(
        key,
        mapping={
            "state": state,
            "status": "offline" if state == "offline" else "online",
        },
    )
    append_worker_op(
        domain=domain,
        worker_id=worker_id,
        op_type="state_change",
        message=f"Worker state changed to {state}",
        details={"from": previous_state, "to": state},
    )
    return {"ok": True, "state": state}


@router.post("/workers/{worker_id}/detach")
def detach_worker(worker_id: str, request: Request):
    """
    Remove an offline worker record from Redis.
    By default requires worker connectivity to be offline and no running jobs.
    Optional query param force=true bypasses those checks.
    """
    r = get_redis()
    ttl = max(2, int(os.getenv("SCHEDULER_HEARTBEAT_TTL", "10")))
    force = _truthy_flag(request.query_params.get("force"))
    domain, key, _data = _resolve_worker_key(request, worker_id)

    hb = r.zscore(f"worker_heartbeats:{domain}", worker_id)
    connectivity_status, _hb_age = _heartbeat_connectivity(hb, ttl)
    if connectivity_status != "offline" and not force:
        raise HTTPException(status_code=409, detail="worker is online; only offline workers can be detached")

    running_jobs = list(r.smembers(f"worker_running_set:{domain}:{worker_id}") or [])
    if running_jobs and not force:
        raise HTTPException(
            status_code=409,
            detail=f"worker has {len(running_jobs)} running job(s); failover or force detach required",
        )

    requeued_count = _requeue_worker_queue(r, domain, worker_id)
    r.zrem(f"worker_heartbeats:{domain}", worker_id)
    r.delete(
        key,
        f"worker_running_set:{domain}:{worker_id}",
        f"worker_metrics:{domain}:{worker_id}:history",
        f"worker_ops:{domain}:{worker_id}",
    )

    append_worker_op(
        domain=domain,
        worker_id=worker_id,
        op_type="detach",
        message="Worker detached from scheduler registry",
        details={"force": force, "requeued_jobs": requeued_count},
    )
    return {"ok": True, "domain": domain, "worker_id": worker_id, "detached": True, "requeued_jobs": requeued_count}


@router.get("/workers/{worker_id}/operations")
def worker_operations(worker_id: str, request: Request):
    r = get_redis()
    domain, _key, _data = _resolve_worker_key(request, worker_id)
    limit = max(20, min(int(request.query_params.get("limit", "200")), 1000))
    raw_events = r.lrange(f"worker_ops:{domain}:{worker_id}", -limit, -1) or []
    events = []
    for raw in raw_events:
        try:
            events.append(json.loads(raw))
        except Exception:
            continue
    events.sort(key=lambda e: float(e.get("ts") or 0), reverse=True)
    return {"worker_id": worker_id, "domain": domain, "events": events}
