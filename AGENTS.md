# Repository Guidelines

## Workflow & Architecture
- Scheduler (`scheduler/`) runs three background loops: `scheduling_loop` dispatches jobs from `job_queue:<domain>:pending` to `job_queue:<domain>:<worker_id>`, `failover_loop` requeues jobs from offline workers, and `schedule_trigger_loop` advances cron/interval jobs. API auth is enforced via `ADMIN_TOKEN` or domain tokens hashed in Mongo/Redis.
- Worker (`worker/`) registers itself in Redis with tags/allowed users/domain token hash, heartbeats every 2s, BLPOPs its queue, tracks `current_running`/`worker_running_set`, streams logs to Redis (per-domain channels), and writes run docs to Mongo via `record_run_start`/`record_run_end`.
- Domains: default `prod` is seeded on scheduler startup; additional domains live in Mongo (`domains` collection) with token hashes cached in Redis. Admin token bypasses domain scoping; domain tokens scope all other requests.
- UI (`ui/`) consumes the scheduler API/SSE for jobs, workers, history, and log streaming. Docker Compose builds and serves it on port 5173; adjust `VITE_API_BASE_URL` as needed.

## Project Structure & Key Modules
- `scheduler/main.py` bootstraps FastAPI + CORS and starts the scheduling/failover/schedule threads.
- `scheduler/api/*` expose jobs, workers, health, events (SSE), logs streaming, history, and admin domain/template management.
- `scheduler/models/*` define Pydantic models for jobs, runs, workers, executors, and scheduling.
- `scheduler/utils/*` house affinity checks, worker selection, failover logic, auth helpers, schedule math, and logging setup.
- `worker/worker.py` registers the worker, maintains heartbeats, and executes jobs concurrently via `ThreadPoolExecutor`.
- `worker/utils/*` contain shell/exec helpers, python env prep (`uv`/venv/system), completion criteria evaluation, concurrency counters, and heartbeats.
- `examples/` holds submission scripts/templates; `deploy/k8s` has manifests; `docker-compose*.yml` define local stacks.

## Run & Test Commands
- Local stack: `ADMIN_TOKEN=<token> docker compose up --build` (scheduler/ui/redis/mongo). Worker-only: `API_TOKEN=<domain_token> WORKER_DOMAIN=prod docker compose -f docker-compose.worker.yml up --build`.
- Dev servers: `uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000` and `npm install && npm run dev` inside `ui/` (set `VITE_API_BASE_URL`).
- Unit tests: `pytest tests/test_scheduler.py tests/test_worker.py`. The end-to-end test is skipped unless the full stack is running.
- Linting/formatting are not configured; match existing style (Python 3.11, 4-space indent, type hints where present).

## Configuration Notes
- Common env vars: `REDIS_URL`, `MONGO_URL`, `MONGO_DB`, `SCHEDULER_HEARTBEAT_TTL`, `CORS_ALLOW_ORIGINS`, `ADMIN_TOKEN`, `ADMIN_DOMAIN`.
- Worker env: `WORKER_DOMAIN`, `WORKER_DOMAIN_TOKEN` (or `API_TOKEN`), `WORKER_ID`, `WORKER_TAGS`, `ALLOWED_USERS`, `MAX_CONCURRENCY`, `WORKER_STATE`, `DEPLOYMENT_TYPE`.
- Docker images target Python 3.11 slim; `uv` is optional but must be present in the image to use the `uv` python environment.

## Known Gaps / Cleanup Targets
- Queue-based routing is not implemented; all dispatching is per worker/domain. If queues are needed, add scheduler-side selection rules and worker registration metadata accordingly.

## Working Agreements
- Commit after each meaningful change with a clear description of what changed and why. Keep commits small and scoped.
- Use `git status`/`git diff` frequently before committing to keep the working tree clean and to avoid drifting config or lockfiles.
- When editing, align affinity/capability expectations across scheduler, worker, and UI to prevent drift between enforcement and presentation.
