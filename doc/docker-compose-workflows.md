# Docker/Compose workflows

Faster local testing and interactive development flows for scheduler, worker, and UI changes.

## Compose files
- `docker-compose.yml` — prod-like stack (scheduler + UI + Redis + Mongo).
- `docker-compose.dev.yml` — dev overlay: mounts source into containers and runs the scheduler with `--reload`; adds a dev worker tied to the same Redis/Mongo.
- `docker-compose.worker.yml` — worker-only (useful when pointing at an existing scheduler stack).

Create a `.env` with at least `ADMIN_TOKEN` and a domain token (for workers) before running these.

## Common workflows
- Prod-like stack: `ADMIN_TOKEN=<token> docker compose up --build` (brings up scheduler/ui/redis/mongo). Use when validating the built assets.
- Fast dev loop (hot reload for Python): `ADMIN_TOKEN=<token> API_TOKEN=<domain_token> docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build redis mongo scheduler worker ui`
  - Scheduler runs `uvicorn --reload` with your local `scheduler/` mounted; Python edits take effect without rebuilding the image.
  - Worker is mounted to your local `worker/`; restart the worker container after changing dependencies.
- UI iteration: run locally for live reload `cd ui && VITE_API_BASE_URL=http://localhost:8000 npm install && npm run dev -- --host 0.0.0.0 --port 5173` (or rely on the Compose-built static UI when not touching the frontend).
- Worker only (attach to an existing scheduler/redis/mongo): `API_TOKEN=<domain_token> WORKER_DOMAIN=prod docker compose -f docker-compose.worker.yml up --build`.
- Build images without running: `docker compose build scheduler worker ui` (add `--build-arg VITE_API_BASE_URL=<url>` if the UI should target a non-default API).

## Helper scripts (repo root)
- `./scripts/dev-up.sh` — start the dev stack (redis/mongo/scheduler/ui + dev worker) with the dev overlay; no args runs `up --build` on core services, otherwise args are passed through.
- `./scripts/dev-down.sh` — stop the dev stack; set `NUKE=1` to also drop volumes.
- `./scripts/worker-up.sh` — run only the worker compose file against an existing scheduler stack.
- `./scripts/build-images.sh` — build scheduler/worker/ui images (respects `VITE_API_BASE_URL` for UI builds).

## Bootstrap test domains quickly
- Create a domain + token: `ADMIN_TOKEN=<admin> ./scripts/create-domain.sh staging` (optional env: `API_BASE`, `DISPLAY`, `DESC`, `TOKEN`). Output prints the token.
- Run a local worker for that domain: `API_TOKEN=<token> WORKER_DOMAIN=staging ./scripts/dev-up.sh worker` (or `./scripts/worker-up.sh --build` against another stack).
- Seed jobs into that domain: `API_BASE=http://localhost:8000 API_TOKEN=<token> python examples/seed_test_jobs.py`.
- Kubernetes workers: `kubectl create secret generic hydra-domain-token --from-literal=API_TOKEN=<token>` then `kubectl set env deployment/hydra-worker WORKER_DOMAIN=staging --from=secret/hydra-domain-token --containers=worker` (ensure the worker image points at the right Redis/Mongo).

## Quick interaction once the stack is up
- Health: `curl http://localhost:8000/health`
- Workers: `curl http://localhost:8000/workers/`
- Seed sample jobs: `API_BASE=http://localhost:8000 API_TOKEN=<domain_token> python examples/seed_test_jobs.py`
- Logs: `docker compose logs -f scheduler` or `docker compose logs -f worker`

## Tips to keep loops fast
- Use `--build` only when dependencies change; for Python edits rely on the dev overlay bind mounts + reload.
- After changing env values, `docker compose restart scheduler worker` is quicker than a full down/up.
- To reset state, `docker compose down -v` clears the Mongo volume; otherwise history persists across runs.
