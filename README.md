# hydra-jobs

A distributed job runner with a FastAPI scheduler, cross‑platform workers, Redis for coordination, MongoDB for job definitions/run history, and a React UI for submission + monitoring. Comes with Docker Compose for a one‑command local stack.

## Overview

- Scheduler service (Python/FastAPI) exposes a REST API to submit jobs, validate definitions, update them, list workers, stream scheduler events (SSE), and expose health. The scheduler dispatches pending jobs to eligible workers, evaluates cron/interval schedules, and performs failover.
- Worker service (Python) registers to Redis, heartbeats, consumes its queue, executes jobs (shell, batch, python, or external binaries) with configurable concurrency, and persists run results to MongoDB including slot/attempt metadata.
- Redis coordinates: job queues, worker heartbeats, and in‑flight job markers.
- MongoDB stores: job definitions, executor configs, job runs (history with slot/attempt/queue latency), and can be queried by API/UI.

## Architecture Diagram

```
        +----------------+             +-----------------+
        |    FastAPI     |  REST API   |   submit_job    |
        |   Scheduler    | <---------  |   (curl/py)     |
        +-------+--------+             +-----------------+
                |                               ^
                |                               |
        dispatch|                               |
                v                               |
        +----------------+      heartbeats       |
        |     Redis      | <---------------------+
        |  queues+state  | -----------------> worker queues
        +--------+-------+                      ^
                 |                              |
                 v                              | execute + report
        +----------------+                      |
        |    Workers     |----------------------+
        |  (Linux/Win)   |   MongoDB (runs/defs)
        +----------------+           |
                                     v
                               +-----------+
                               |  MongoDB  |
                               +-----------+
```

## How Scheduler Works

- BLPOP `job_queue:pending` and fetch the job definition from MongoDB.
- Discover online workers via `worker_heartbeats` TTL; filter by:
  - `max_concurrency > current_running`
  - OS, tags, and allowed_users affinity
- Select best worker by lowest load and RPUSH the job ID to `job_queue:<worker_id>`.
- Workers record run documents when they start executing a job (including slot/attempt metadata and completion details).
- A dedicated schedule loop evaluates cron/interval plans and enqueues due jobs (`schedule.next_run_at <= now`), advancing the next tick after each dispatch.
- Periodically scan for stale heartbeats; for offline workers requeue their running jobs.

## How Workers Work

- Register in `workers:<worker_id>` with OS, tags, allowed users, and `max_concurrency`.
- Send heartbeats every 2 seconds to `worker_heartbeats`.
- BLPOP from `job_queue:<worker_id>`; for each job:
  - Atomically `HINCRBY` current_running and track `worker_running_set:<worker_id>`.
  - Start a run entry (status=running); execute the command with OS‑appropriate shell.
  - Update Mongo with stdout, stderr, return code, and status; decrement counters and clear Redis markers.

## Redis Usage

- `workers:<domain>:<worker_id>`: hash with worker metadata, `max_concurrency`, `current_running`, status
- `worker_heartbeats:<domain>`: sorted set `id -> timestamp`
- `job_queue:<domain>:pending`: pending jobs per domain (priority zset)
- `job_queue:<domain>:<worker_id>`: per‑worker list of job IDs
- `job_running:<domain>:<job_id>`: hash with `worker_id`, `heartbeat`, `user`
- `worker_running_set:<domain>:<worker_id>`: set of active job IDs
- `token_hash:<domain>` and `token_hash:<hash>:domain`: cache of domain tokens (hashed)

## MongoDB Usage

Collections:
- `domains` — domain metadata and token hash (`domain`, `display_name`, `description`, `token_hash`)
- `job_definitions` — job documents with `_id` (string), name, user, affinity, executor config (python/shell/batch/external), retries, timeout, schedule metadata (mode, cron/interval, next run), completion criteria, timestamps, **domain**
- `job_runs` — run history with job_id, user, worker_id, timestamps, status, returncode, stdout, stderr, concurrency slot, attempt count, queue latency, executor type, completion reason, **domain**

## Quick Start

- Prereqs: Docker + Docker Compose
- Build images (from repo root):

```
docker build -t hydra-scheduler:latest scheduler
docker build -t hydra-worker:latest worker
docker build -t hydra-ui:latest ui
```

### Run core stack (scheduler/ui/redis/mongo)

```
ADMIN_TOKEN=<your_admin_token> docker compose up --build
```

### Run a worker separately

Set a domain token for the worker (must match the domain in Mongo, e.g., created via Admin UI):

```
API_TOKEN=<domain_token> WORKER_DOMAIN=prod \ 
REDIS_URL=redis://localhost:6379/0 MONGO_URL=mongodb://localhost:27017 \ 
docker compose -f docker-compose.worker.yml up --build
```

Once running:

```
python examples/submit_job.py
# or
bash examples/submit_job.sh

```

Check status:

```
curl http://localhost:8000/health
curl http://localhost:8000/workers/
curl http://localhost:8000/events/stream   # SSE stream
```
Access the React UI at `http://localhost:5173` (served by Docker Compose via the `ui` service). If you run the API elsewhere, adjust `docker-compose.yml`’s `VITE_API_BASE_URL` build arg or run the UI locally via `npm run dev`.

**CORS note:** The scheduler enables CORS for `http://localhost:5173` and `http://localhost:8000` by default so the bundled UI can talk to the API. Override `CORS_ALLOW_ORIGINS` (comma-separated or `*`) if you host the UI/API on different domains.

**Persistent history:** Mongo now uses a named Docker volume (`mongo-data`) so job definitions and run history survive container restarts.

### Domains / Tokens (multi-tenant)

- Scheduler: set `ADMIN_TOKEN` (admin domain defaults to `admin`). Domains/tokens live in Mongo (`domains` collection). No domains are pre-seeded unless you set `SEED_DOMAINS=1` (dev compose).
- Workers: set `WORKER_DOMAIN=<domain>` and **required** `WORKER_DOMAIN_TOKEN=<matching token>`; workers register with a token hash and are accepted only for their domain.
- Redis/Mongo are scoped per domain; admin token can see all domains, others only their own. Domain tokens are resolved from Mongo by hash, not from env.
- UI: provide a token (admin or domain) via `.env`/localStorage; admin token shows the Admin page to manage domains and tokens.

### Smoke-test jobs

Seed common scenarios for quick validation:

```bash
API_BASE=http://localhost:8000 API_TOKEN=changeme python examples/seed_test_jobs.py
```

Creates quick shell, long-running shell, failing, python, and cron jobs to validate scheduling, logs, and queue handling.

## Write Your Own Worker

- Set env vars: `WORKER_ID`, `WORKER_TAGS` (comma‑sep), `ALLOWED_USERS` (comma‑sep), `MAX_CONCURRENCY`.
- Ensure it registers in `workers:<id>`, heartbeats to `worker_heartbeats`, and processes `job_queue:<id>`.
- Respect atomic counters (`current_running`) and `worker_running_set:<id>` membership.

## Submit Jobs

POST `http://localhost:8000/jobs/` with JSON body:

```
{
  "name": "test-echo",
  "user": "rich",
  "affinity": { "os": ["linux"], "tags": [], "allowed_users": ["rich"] },
  "executor": {
    "type": "shell",
    "script": "echo 'hello world'",
    "shell": "bash"
  },
  "schedule": {
    "mode": "interval",
    "interval_seconds": 300,
    "enabled": true
  },
  "completion": {
    "exit_codes": [0],
    "stdout_contains": ["hello"],
    "stdout_not_contains": [],
    "stderr_contains": [],
    "stderr_not_contains": []
  },
  "retries": 0,
  "timeout": 10
}
```

Then query:

- `GET /jobs/{job_id}` — job metadata
- `GET /jobs/{job_id}/runs` — run history
- `GET /overview/jobs` — aggregate stats + last run details/log tails for every job
- `PUT /jobs/{job_id}` — update job configuration/executor
- `POST /jobs/{job_id}/validate` or `/jobs/validate` — dry-run validation
- `POST /jobs/{job_id}/run` — enqueue a manual run immediately, regardless of schedule
- `POST /jobs/adhoc` — create + run a one-off job (schedule forced to immediate, disabled after dispatch)
- `GET /workers/` — workers
- `GET /events/stream` — real-time scheduler events (SSE)
- `GET /health` — scheduler health

### Scheduling

- `schedule.mode="immediate"` (default) enqueues the job as soon as it is created.
- `schedule.mode="interval"` runs every `interval_seconds`, starting at `start_at` (defaults to now); `end_at` stops future runs, and setting `enabled=false` pauses the schedule.
- `schedule.mode="cron"` accepts standard cron expressions (UTC) plus optional `start_at`/`end_at`. Each enqueue emits a `job_scheduled` SSE event.
- `POST /jobs/validate` returns `next_run_at` so you can preview when the next kick-off will occur.
- Use `POST /jobs/{job_id}/run` to force a run immediately, even if the schedule is paused/not due.

### Adhoc & Manual Jobs

- `POST /jobs/adhoc` accepts the same payload as `/jobs/` but forces the schedule to `immediate` + `enabled=false`, ensuring the definition runs exactly once (still recorded in Mongo for history).
- `POST /jobs/{job_id}/run` is useful for re-running a scheduled job on demand (e.g., after a fix) without altering its cadence.

### Completion Criteria

Every job can define pass/fail rules beyond exit codes:

- `completion.exit_codes` (default `[0]`) lists the success return codes.
- `stdout_contains` / `stderr_contains` require substrings to appear; `stdout_not_contains` / `stderr_not_contains` ensure substrings do **not** appear.
- All configured rules must pass for a run to be marked `success`; failures capture the first unmet rule in `completion_reason` and, if retries remain, trigger another attempt.

### Python Runtimes & Dependencies

When using the `python` executor, you can control the runtime per job:

- **Environment types:** `system` (default), `venv`, or `uv`. Pick `uv` to run via [uv](https://github.com/astral-sh/uv) with an explicit Python version and per-job dependencies. Use `venv` to point at an existing virtualenv (via `environment.venv_path`) or let Hydra create a temporary one automatically.
- **Python versions:** Set `environment.python_version` (e.g., `3.10` or `python3.10`) and the worker runs the script with that interpreter (or `uv --python` when using uv).
- **Dependencies:** Provide packages in `environment.requirements` (one per line in the UI) and/or a `requirements_file`. Hydra installs them into the selected environment before executing your code.
- Ensure the worker image contains the required tooling (`uv`, alternate Python binaries, pip) for the environments you enable. When Hydra creates a temporary venv, it cleans it up after the job finishes.

### React Control Plane

The `ui/` directory hosts a Vite + React frontend for building/validating jobs, running them on demand, viewing job history & worker health, and tailing scheduler events via SSE. Docker Compose builds and serves this UI automatically at `http://localhost:5173`. For local development, run `npm install && npm run dev` inside `ui/` and set `VITE_API_BASE_URL` to the scheduler URL.

## Kubernetes Deployment

You can deploy the same stack to a cluster using the manifests under `deploy/k8s`:

1. Build/push your images (or load them into the cluster):
   ```
   docker build -t hydra-scheduler:latest scheduler
   docker build -t hydra-worker:latest worker
   ```
   Customize `deploy/k8s/hydra.yaml` if you host the images in a registry (e.g., set `image: ghcr.io/you/hydra-scheduler:TAG`).
2. Apply the manifests:
   ```
   kubectl apply -f deploy/k8s/hydra.yaml
   ```
   This creates:
   - `redis` and `mongo` Deployments/Services
   - A scheduler Deployment + Service on port 8000
   - A default worker Deployment scaled to 2 replicas
3. Port-forward the scheduler to reach the API/UI locally:
   ```
   kubectl -n hydra-jobs port-forward svc/scheduler 8000:8000
   ```
4. Run the React UI locally (pointing `VITE_API_BASE_URL=http://localhost:8000`) or expose the scheduler through your preferred ingress.

### Multiple Execution Environments in Kubernetes

Workers are the execution boundary, so each distinct runtime (e.g., GPU-enabled, Windows emulation, specific tooling) becomes its own Deployment:

- Build container images that contain the tooling/runtime you need. Reference those images in dedicated worker manifests.
- Use `WORKER_TAGS` / `ALLOWED_USERS` env vars so the scheduler can target the correct pool.
- Apply `nodeSelector`, `tolerations`, and `affinity` to bind a worker Deployment to the nodes that satisfy its requirements (e.g., GPUs, Windows nodes, ARM, etc.).
- Scale each worker Deployment independently, or create a `StatefulSet` if you need stable `WORKER_ID`s. By default, the provided manifest sets `WORKER_ID` to the pod name via the Downward API.
- For isolated namespaces/tenants, duplicate the worker Deployment with different Redis/Mongo URLs or credentials.

This mirrors Docker-based environments: each worker image encapsulates the required interpreter/binaries, and the scheduler simply routes jobs based on tags and affinity.

## Debugging Tips

- Redis keys: inspect with `redis-cli` (`keys workers:*`, `zrange worker_heartbeats 0 -1 withscores`).
- Mongo collections: `job_definitions`, `job_runs`.
- Logs: adjust `LOG_LEVEL` env to `DEBUG`.
- If no eligible worker, the scheduler requeues and retries — check worker OS/tags/users.

## Roadmap

- Pluggable executors (containers, SSH).
- Backoff with dead‑letter queues.
- Job scheduling / cron support.
- Authentication and multi‑tenant namespaces.
