import json
import os
import time

from fastapi import APIRouter, Request

from ..mongo_client import get_db
from ..orchestrator import HEARTBEAT_TTL, ORCHESTRATOR_HEARTBEAT_KEY
from ..redis_client import get_redis

router = APIRouter()


def demo_mode_enabled() -> bool:
    """Whether demo/test UI affordances (seed-jobs buttons, executor smoke
    test, dependency-graph demo, admin quick-actions) should render.

    Purely a UI-declutter switch, not an authorization boundary: every
    action those elements trigger goes through already-authorized endpoints
    (POST /jobs/, POST /admin/domains, etc.) that work identically whether
    this is on or off. Default off so a stock deployment's UI stays clean;
    set HYDRA_DEMO_MODE=true (docker-compose.dev.yml does this by default;
    the Helm chart's demoMode.enabled value controls it for Kubernetes).
    """
    return os.getenv("HYDRA_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/health")
def health(request: Request):
    r = get_redis()
    domain = getattr(request.state, "domain", "prod")
    # Ping Mongo too — job/admin APIs depend on it, so a Redis-only check would
    # keep reporting "ok" (and keep passing Docker/k8s readiness) during a Mongo
    # outage. Letting this raise on failure is intentional: FastAPI turns it into
    # a 500, which is what marks the container/pod unhealthy.
    get_db().command("ping")
    # Return lightweight health stats
    workers_count = len(list(r.scan_iter(f"workers:{domain}:*")))
    pending = r.zcard(f"job_queue:{domain}:pending")
    return {
        "status": "ok",
        "workers": workers_count,
        "pending_jobs": pending,
        "demo_mode": demo_mode_enabled(),
    }


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
