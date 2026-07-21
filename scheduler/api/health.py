import json
import time

from fastapi import APIRouter, Request

from ..orchestrator import HEARTBEAT_TTL, ORCHESTRATOR_HEARTBEAT_KEY
from ..redis_client import get_redis

router = APIRouter()


@router.get("/health")
def health(request: Request):
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    # Return lightweight health stats
    workers_count = len(list(r.scan_iter(f"workers:{domain}:*")))
    pending = r.zcard(f"job_queue:{domain}:pending")
    return {"status": "ok", "workers": workers_count, "pending_jobs": pending}


@router.get("/health/orchestration")
def orchestration_health():
    """Report whether the control-plane orchestrator is alive and making progress.

    Reads the heartbeat key written by the running ``OrchestratorManager``
    (either the combined API/orchestrator process or the standalone
    ``orchestrator_entrypoint``).

    Returns:
    - ``status: ok``      — heartbeat is fresh (age < TTL).
    - ``status: stale``   — heartbeat exists but is older than expected.
    - ``status: unknown`` — no heartbeat found; orchestrator may not be running.
    """
    r = get_redis()
    raw = r.get(ORCHESTRATOR_HEARTBEAT_KEY)
    if not raw:
        return {
            "status": "unknown",
            "message": (
                "No orchestrator heartbeat found. "
                "The control-plane may not be running. "
                "In combined mode start the scheduler normally; "
                "in separated mode run 'python -m scheduler.orchestrator_entrypoint'."
            ),
        }
    try:
        data = json.loads(raw)
    except Exception:
        return {"status": "unknown", "message": "Malformed heartbeat payload"}

    ts = data.get("ts")
    if not ts:
        return {"status": "unknown", "message": "Heartbeat payload missing timestamp"}

    age_seconds = round(time.time() - ts, 1)
    loops = data.get("loops", [])

    if age_seconds > HEARTBEAT_TTL:
        return {"status": "stale", "age_seconds": age_seconds, "loops": loops}

    return {"status": "ok", "age_seconds": age_seconds, "loops": loops}
