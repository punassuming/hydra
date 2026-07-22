import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin import router as admin_router
from .api.ai import router as ai_router
from .api.credentials import router as credentials_router
from .api.domain import router as domain_router
from .api.events import router as events_router
from .api.health import router as health_router
from .api.history import router as history_router
from .api.jobs import router as jobs_router
from .api.logs import router as logs_router
from .api.workers import router as workers_router
from .orchestrator import OrchestratorManager, create_standard_orchestrator
from .startup import ensure_admin_token, ensure_domains_seeded, warn_credential_encryption_key
from .utils.auth import enforce_api_key
from .utils.logging import setup_logging

log = setup_logging("scheduler.main")

# ---------------------------------------------------------------------------
# Runtime mode
# ---------------------------------------------------------------------------
# HYDRA_MODE controls whether orchestration loops are co-located with the API.
#
#   combined  (default) — API + all orchestration loops in one process.
#                         Preserves backward-compatible single-service behaviour.
#   api       — API only.  No orchestration loops are started.  Run
#               ``python -m scheduler.orchestrator_entrypoint`` separately.
#
HYDRA_MODE = os.getenv("HYDRA_MODE", "combined")

# Module-level orchestrator instance — set during startup when running in combined mode.
_orchestrator: OrchestratorManager | None = None


def on_startup():
    global _orchestrator
    ensure_admin_token()
    warn_credential_encryption_key()
    ensure_domains_seeded()
    if HYDRA_MODE == "api":
        log.info(
            "HYDRA_MODE=api: API service started without orchestration loops. "
            "Run 'python -m scheduler.orchestrator_entrypoint' for the control-plane."
        )
    else:
        log.info("HYDRA_MODE=%s: starting orchestration loops alongside API", HYDRA_MODE)
        _orchestrator = create_standard_orchestrator()
        _orchestrator.start()


def on_shutdown():
    if _orchestrator is not None:
        log.info("Stopping orchestration loops")
        _orchestrator.stop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    on_startup()
    yield
    on_shutdown()


app = FastAPI(title="hydra-jobs scheduler", lifespan=lifespan)
app.middleware("http")(enforce_api_key)

cors_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip() and origin.strip() != "*"]
allow_all = "*" in [o.strip() for o in cors_env.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else (allow_origins or ["http://localhost:5173", "http://localhost:8000"]),
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.include_router(jobs_router)
app.include_router(workers_router)
app.include_router(health_router)
app.include_router(events_router)
app.include_router(history_router)
app.include_router(logs_router)
app.include_router(admin_router)
app.include_router(credentials_router)
app.include_router(domain_router)
app.include_router(ai_router)
