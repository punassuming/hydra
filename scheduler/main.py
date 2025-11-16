import os
import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.jobs import router as jobs_router
from .api.workers import router as workers_router
from .api.health import router as health_router
from .api.events import router as events_router
from .scheduler import scheduling_loop, failover_loop, schedule_trigger_loop
from .utils.logging import setup_logging


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
)
app.include_router(jobs_router)
app.include_router(workers_router)
app.include_router(health_router)
app.include_router(events_router)


stop_event = threading.Event()


@app.on_event("startup")
def on_startup():
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
