import os
import threading
import secrets
import hashlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.jobs import router as jobs_router
from .api.workers import router as workers_router
from .api.health import router as health_router
from .api.events import router as events_router
from .api.history import router as history_router
from .api.logs import router as logs_router
from .api.admin import router as admin_router
from .api.ai import router as ai_router
from .scheduler import scheduling_loop, failover_loop, schedule_trigger_loop
from .utils.logging import setup_logging
from .utils.auth import enforce_api_key
from .redis_client import get_redis
from .mongo_client import get_db


log = setup_logging("scheduler.main")

app = FastAPI(title="hydra-jobs scheduler")
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
app.include_router(ai_router)
app.middleware("http")(enforce_api_key)

stop_event = threading.Event()


def _ensure_domains_seeded():
    r = get_redis()
    db = get_db()
    # Always cache existing hashes
    for doc in db.domains.find({}):
        domain = doc.get("domain")
        token_hash = doc.get("token_hash")
        if not domain or not token_hash:
            continue
        r.sadd("hydra:domains", domain)
        r.set(f"token_hash:{domain}", token_hash)
        r.set(f"token_hash:{token_hash}:domain", domain)
    # Optional seeding (used by dev compose)
    if db.domains.count_documents({}) == 0:
        token = secrets.token_hex(24)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        db.domains.insert_one({"domain": "prod", "display_name": "Production", "description": "Production", "token_hash": token_hash})
        r.sadd("hydra:domains", "prod")
        r.set(f"token_hash:prod", token_hash)
        r.set(f"token_hash:{token_hash}:domain", "prod")
        log.warning("Seeded default prod domain with token: %s", token)


def _ensure_admin_token():
    global os
    from . import utils
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token:
        admin_token = secrets.token_hex(24)
        os.environ["ADMIN_TOKEN"] = admin_token
        log.warning("Generated ADMIN_TOKEN: %s", admin_token)
    # update auth module variable for consistency
    try:
        from .utils import auth
        auth.ADMIN_TOKEN = admin_token
    except Exception:
        pass


@app.on_event("startup")
def on_startup():
    _ensure_admin_token()
    _ensure_domains_seeded()
    log.info("Starting scheduler background threads")
    app.state.scheduler_thread = threading.Thread(target=scheduling_loop, args=(stop_event,), daemon=True)
    app.state.failover_thread = threading.Thread(target=failover_loop, args=(stop_event,), daemon=True)
    app.state.schedule_thread = threading.Thread(target=schedule_trigger_loop, args=(stop_event,), daemon=True)
    app.state.scheduler_thread.start()
    app.state.failover_thread.start()
    app.state.schedule_thread.start()


@app.on_event("shutdown")
def on_shutdown():
    log.info("Stopping scheduler background threads")
    stop_event.set()
    th1 = getattr(app.state, "scheduler_thread", None)
    th2 = getattr(app.state, "failover_thread", None)
    th3 = getattr(app.state, "schedule_thread", None)
    if th1:
        th1.join(timeout=2)
    if th2:
        th2.join(timeout=2)
    if th3:
        th3.join(timeout=2)
