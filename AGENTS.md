# Hydra Jobs

## Project Overview

Hydra Jobs is a distributed job runner designed for flexibility and scalability. It features a FastAPI-based scheduler, cross-platform workers (Python and Go), and a React-based user interface.

**Key Components:**

*   **Scheduler Service:** A Python FastAPI application that exposes a REST API for job management. It handles job submission, validation, scheduling (cron/interval), and dispatching to workers via Redis. It also supports Server-Sent Events (SSE) for real-time updates.
    *   **AI Integration:** Uses Google Gemini or OpenAI for generating job definitions from natural language, analyzing job failures, diffing a failed run against the job's last success, and estimating expected run duration. A separate, LLM-free "Investigate" set of canned checks (`scheduler/api/investigations.py`) covers common ops questions without needing a provider key.
*   **Worker Service:** Two interchangeable implementations that speak the same Redis protocol/env-var contract, so pools of each can run side by side against one scheduler:
    *   **Python worker** (`worker/`) — full feature set: shell/python/batch/powershell/sql/http/external/sensor executors, Git source provisioning, Linux impersonation, Kerberos pre-auth, and a Windows bootstrap/watchdog (Task Scheduler or a Windows Service via NSSM).
    *   **Go worker** (`go-worker/`) — lighter-weight: shell/http/external executors and Git source provisioning, no SQL executor or impersonation/Kerberos.
*   **UI:** A React application built with Vite, TypeScript, and Ant Design. It provides a visual interface for monitoring jobs, workers, and run history, with integrated AI tools and canned investigations.
*   **Data Store:**
    *   **Redis:** Used for job queues, worker coordination, heartbeats, and pub/sub.
    *   **MongoDB:** Stores persistent data including job definitions, run history, and domain metadata.

## Architecture

*   **Language:** Python 3.13 (CI target; minimum 3.11 supported), Go (worker, CI target per `go-worker/go.mod`), TypeScript (Frontend)
*   **Frameworks:** FastAPI (Scheduler), React + Vite (UI)
*   **Database:** MongoDB (v6.0 recommended, v5.0 for broader CPU support), Redis (v7-alpine)
*   **AI Provider:** Google Gemini (requires `GEMINI_API_KEY`) or OpenAI (requires `OPENAI_API_KEY`)
*   **Infrastructure:** Docker & Docker Compose (single or multi worker-pool), Kubernetes via the Helm chart in `deploy/helm/hydra/`, Windows Task Scheduler/Service for bare-metal workers

## Workflow & Architecture (Internal Details)

- Scheduler (`scheduler/`) runs eight background loops: `scheduling_loop` dispatches jobs from `job_queue:<domain>:pending` to `job_queue:<domain>:<worker_id>`, `failover_loop` requeues jobs from offline workers and prunes stale offline worker records after a retention window, `schedule_trigger_loop` advances cron/interval jobs, `run_event_loop` consumes `run_events:<domain>` from Redis and persists run docs in Mongo, `timeout_enforcement_loop` marks stale runs as failed, `sla_monitoring_loop` checks SLA deadlines, `backfill_dispatch_loop` handles historical backfill runs, and `redis_acl_reconciliation_loop` (every `SCHEDULER_ACL_RECONCILE_INTERVAL`s, default 30) re-applies each domain's persisted worker Redis ACL user so a Redis-only restart (Redis crashes/restarts without the scheduler also restarting) self-heals instead of leaving worker auth broken until an operator intervenes. There is **no** scheduler-side sensor evaluation loop — sensor jobs are dispatched to workers like any other job type.
- **Control-plane separation**: The scheduler supports two runtime modes via `HYDRA_MODE`:
  - `combined` (default): API + all orchestration loops run in one process (backward compatible, easiest for local dev).
  - `api`: API only; no background loops. Run `python -m scheduler.orchestrator_entrypoint` as a separate process for the control-plane.
  - The `OrchestratorManager` in `scheduler/orchestrator.py` owns loop registration, thread startup, stop signaling, and writes a heartbeat to `hydra:orchestrator:heartbeat` in Redis (TTL 30s, refreshed every 10s). Use `GET /health/orchestration` to check orchestrator liveness independently of API health.
- Terminal failures can trigger `on_failure_webhooks` and SMTP email alerts (`on_failure_email_to` + `on_failure_email_credential_ref`).
- Scheduler admin API can provision domain-scoped Redis ACL worker access (`/admin/domains/{domain}/redis_acl/rotate`) and returns credentials for that domain; workers use `DOMAIN` as Redis username and `REDIS_PASSWORD` as secret.
- Worker Redis ACL username is the domain name itself (legacy hashed usernames are cleaned up on rotation/delete).
- Redis ACL credentials are persisted in Mongo domain metadata when created/rotated, and scheduler startup re-applies stored ACL users/passwords to Redis so worker auth survives Redis restarts/recreates without forced credential rotation.
- Scheduler worker APIs include:
  - `GET /workers/` with runtime + 30m metrics summary (memory/process/load), running jobs/users, plus clear `connectivity_status` and `dispatch_status`.
  - `GET /workers/{worker_id}/metrics` for time-series points.
  - `GET /workers/{worker_id}/timeline` for per-worker execution spans (for Gantt/timeline UI).
  - `GET /workers/{worker_id}/operations` for operational timeline events (start/restart/dispatch/run lifecycle/state changes/failover).
  - `POST /workers/{worker_id}/state` with JSON body `{ "state": "online|draining|offline" }` (`disabled` accepted as legacy alias).
  - `GET /overview/queue` for domain-scoped `pending` queue rows and `upcoming` scheduled jobs (supports `pending_limit`/`upcoming_limit`). Each pending item includes `no_worker_count`; response includes `pending_total` per domain.
  - `GET /overview/pressure` for per-domain backpressure summary: pending depth, stalled/starvation counts, per-worker dispatch queue depths, online worker count, total running vs capacity.
  - `POST /workers/{worker_id}/detach` to remove an offline worker record from Redis registry (optionally `?force=true`), requeuing worker-queue envelopes back to domain pending queue.
- Scheduler domain self-service APIs (domain token or admin token scoped by `domain`):
  - `GET /domain/settings`, `PUT /domain/settings`
  - `POST /domain/token/rotate`
  - `POST /domain/redis_acl/rotate`
- Domain credential APIs for non-admin users:
  - `GET /credentials/`, `POST /credentials/`, `PUT /credentials/{name}`, `DELETE /credentials/{name}`
- Worker (`worker/`) registers itself in Redis with tags/allowed users/domain token hash, heartbeats every 2s, BLPOPs its queue, tracks `current_running`/`worker_running_set`, streams logs to Redis (per-domain channels), emits run events to `run_events:<domain>`, and records worker operations to `worker_ops:<domain>:<worker_id>`.
- Worker no longer mutates global domain registry keys; worker Redis writes are domain-scoped to heartbeat/status/queue/log keys.
- Worker heartbeat stores rolling metrics in Redis (`worker_metrics:<domain>:<worker_id>:history`) including `memory_rss_mb`, `process_count`, and Linux load averages.
- Jobs support `bypass_concurrency`; scheduler can dispatch these even when workers are at quota, and workers execute them outside normal `ThreadPoolExecutor` limits. The scheduler logs a warning when dispatching a bypass job to an overloaded worker. A soft cap (`SCHEDULER_BYPASS_MAX_EXTRA`) can limit how many bypass jobs each worker carries above its normal concurrency limit.
- **No-worker starvation tracking**: `job_enqueue_meta:<domain>:<job_id>` records `no_worker_count` (incremented each time a job is requeued due to no eligible worker). A starvation warning is logged when `no_worker_count` reaches `SCHEDULER_STARVATION_WARN_THRESHOLD` (default 5). The count is visible in `/overview/queue` and `/overview/pressure`.
- **Failover drains per-worker queue**: `failover_loop` / `requeue_jobs_for_worker` now recovers both running jobs (from `worker_running_set`) AND dispatched-but-not-started envelopes from `job_queue:<domain>:<worker_id>`, preventing silent job loss when a worker dies between dispatch and BLPOP.
- Executors support Linux-only impersonation and Kerberos bootstrap: `executor.impersonate_user` and `executor.kerberos.{principal,keytab,ccache}`. Kerberos credential cache is destroyed (`kdestroy`) in a `finally` block immediately after the job finishes. The `keytab` path is masked (`"********"`) in all job API responses.
- **Credential domain validation**: the `?domain=` query parameter on admin credential endpoints is validated against the live `hydra:domains` Redis set; unknown domains receive a 404.
- **Git PAT hygiene**: `worker/utils/git.py` injects the PAT into the HTTPS clone URL only for the network operation, then rewrites `origin` in `.git/config` to the clean URL before the workspace is cached, so tokens do not persist on disk.
- **SQL temp file security**: SQL driver scripts are written via `tempfile.mkstemp()` (mode `0o600`) so the connection URI is never world-readable during execution.
- **Sensor executor** (`executor.type == "sensor"`): dispatched and executed entirely on workers. The worker polls an HTTP endpoint or SQL query at `poll_interval_seconds` intervals. Scheduler resolves `credential_ref` at dispatch time so the worker needs no MongoDB access. No scheduler-side sensor evaluation loop exists.
- **Worker capabilities are fail-closed**: `_detect_capabilities()` in `worker/executor.py` only advertises an executor type after a concrete preflight check (e.g., `shell` requires a shell binary to execute successfully; `sql` requires Python AND a DB driver; `sensor` is always present since HTTP sensor uses stdlib). `startup_duration_ms` is recorded in worker registration metadata and the start/restart operation event.
- **Run timing fields** in `run_end` events (persisted to `job_runs`): `queue_latency_ms`, `total_run_ms`, `source_fetch_ms` (source provisioning time), `env_prep_ms` (Python env preparation time).
- Domains: default `prod` is seeded on scheduler startup; additional domains live in Mongo (`domains` collection) with token hashes cached in Redis. Admin token bypasses domain scoping; domain tokens scope all other requests.
- Domain naming is strict in admin APIs: `2-63` chars, lowercase letters/numbers with optional `_`/`-`, and must start/end with alphanumeric.
- UI (`ui/`) consumes the scheduler API/SSE for jobs, workers, history, and log streaming. Docker Compose builds and serves it on port 5173; adjust `VITE_API_BASE_URL` as needed.
- UI auth/UX notes:
  - Login gate: when unauthenticated, only the auth modal/screen is shown.
  - Auth modal clearly separates `Domain Token` and `Admin Token` sign-in modes; admin mode no longer asks for a domain in the same step.
  - Header has tabbed nav for Operate/Observe/Workers, a separate Admin button beside settings, persistent dark/light toggle, and a Settings drawer for domain/token/admin actions.
  - Admin page is also used for domain self-service when logged in with a domain token (domain settings + credentials for active domain).
  - Worker detail page includes metrics trend plotting + concurrency-lane timeline/Gantt + operational event timeline.
  - Workers main page includes an aggregated Execution/Business timeline section (all workers) for recent run spans and operational events.
  - Job detail page supports in-place editing of existing jobs and quick activate/deactivate (schedule enabled) actions.
  - Logs view supports search/highlight, parsed/raw modes, expansion, and copy actions.
  - AI log helper supports multiple analysis modes (failure fix, summary, error extraction, retry tuning, custom question).
  - Theme and key panel states persist via localStorage.

## Project Structure & Key Modules

- `scheduler/main.py` bootstraps FastAPI + CORS, reads `HYDRA_MODE`, and (in `combined` mode) starts all orchestration loops via `OrchestratorManager`. Startup and shutdown are wired via a FastAPI `lifespan` context manager (`@asynccontextmanager`); the underlying `on_startup()` and `on_shutdown()` functions remain callable directly for tests.
- `scheduler/startup.py` — shared initialisation helpers (`ensure_admin_token`, `ensure_domains_seeded`) used by both the API and the standalone orchestrator entrypoint.
- `scheduler/orchestrator.py` — `OrchestratorManager` (loop registry, thread management, Redis heartbeat) and `create_standard_orchestrator()` factory.
- `scheduler/orchestrator_entrypoint.py` — standalone control-plane process; run with `python -m scheduler.orchestrator_entrypoint` when `HYDRA_MODE=api`.
- `scheduler/api/*` expose jobs, workers, health, events (SSE), logs streaming, history, and admin domain/template management.
- `scheduler/api/workers.py` — worker list/state + metrics/timeline endpoints.
- `scheduler/api/ai.py` — AI endpoints: `generate_job` (NL → job JSON), `analyze_run` (single-run log analysis), `predict_duration` (historical duration percentiles, no LLM), `diagnose_regression` (diffs a failed run against the job's last success + duration baseline, returns a structured root-cause hypothesis). `_call_llm()` is the single Gemini/OpenAI dispatch point all four share where applicable; `duration_percentiles()` is shared by `predict_duration`, `diagnose_regression`, and the `long_running_outliers` investigation.
- `scheduler/api/investigations.py` — canned, LLM-free operational checks (`failed_recent`, `long_running_outliers`, `flaky_jobs`, `never_succeeded`) exposed as `GET /investigations/` (catalog) and `GET /investigations/{key}` (run one). Deliberately does not call an LLM — every check is a fixed, whitelisted query, so it needs no provider API key and returns instantly.
- `scheduler/models/*` define Pydantic models for jobs, runs, workers, executors, and scheduling.
- `scheduler/utils/*` house affinity checks, worker selection, failover logic, auth helpers, schedule math, and logging setup.
- `worker/worker.py` registers the worker, maintains heartbeats, executes jobs, emits `run_start`/`run_end` events to Redis, and records worker operation events.
- `worker/utils/*` contain shell/exec helpers, python env prep (`uv`/venv/system), completion criteria evaluation, concurrency counters, and heartbeats.
- `worker/utils/git.py` — Git clone/checkout logic. PAT is injected for the network operation only; the remote URL is rewritten to strip credentials before the workspace is cached.
- `worker/executor.py` — Job execution engine (shell/python/batch/powershell/sql/http/external/sensor) with git source support.
- `worker/runtime.py` — Host runtime discovery, configured tool paths, and fail-closed capability detection.
- `worker/executor.py` — also handles Linux impersonation + Kerberos pre-auth when configured.
- `worker/__main__.py` — CLI entry point; dispatches to `worker_main()` (default) or `bootstrap.main()` when the first argument is `bootstrap`.
- `worker/bootstrap.py` — Windows worker bootstrap/watchdog: `BootstrapConfig` model, PID-lock helpers, watchdog loop, and `action_install`/`action_remove`/`action_run`/`action_validate` functions. CLI: `python -m worker bootstrap <install|remove|run|validate>`.
- `worker/windows_tasks.py` — Thin wrapper around `schtasks` for Windows Task Scheduler management. All public functions raise `RuntimeError` on non-Windows platforms. (A Windows Service alternative via NSSM wraps the same `bootstrap run` watchdog with no code changes — docs only, see `docs/windows-worker-bootstrap.md`.)
- `go-worker/` — Go worker implementation, same Redis protocol/env-var contract as the Python worker. `main.go` entry point; `internal/worker/worker.go` (dispatch loop + heartbeat file for liveness probes), `internal/executor/executor.go` (shell/http/external only — no SQL/impersonation/Kerberos), `internal/source/source.go` (Git provisioning), `internal/workspace/cache.go`, `internal/config/config.go`, `internal/redisclient/client.go`. Tested with `go test ./...`; no Windows bootstrap equivalent (Python-only).
- `ui/src/App.tsx` — Main React component; header holds the Admin button and the "Investigate" button that opens `InvestigateDrawer`.
- `ui/src/api/` — API client with domain-scoped token management; `ui/src/api/investigations.ts` is the client for the canned-checks tool.
- `ui/src/components/JobForm.tsx` — Job creation form with AI generation (re-exports the decomposed `job-form/` module).
- `ui/src/components/JobRuns.tsx` — Run history with AI failure analysis.
- `ui/src/components/FailureInsight.tsx` — AI Log Assistant + "Compare vs Last Success" (Run Diff Copilot) on a run's log view.
- `ui/src/components/InvestigateDrawer.tsx` — canned-investigations drawer; `ui/src/components/ProviderSelect.tsx` — shared Gemini/OpenAI picker used by every AI feature.
- `examples/` holds submission scripts/templates; `deploy/helm/hydra` has the Kubernetes Helm chart; `docker-compose.yml` + `docker-compose.worker.yml`/`docker-compose.worker.go.yml` (single pool) or `docker-compose.workers.yml` (multiple pools side by side) + `docker-compose.separated.yml`/`docker-compose.dev.yml` define local stacks.
- `tests/` — Backend integration and unit tests.
- `tests/test_ai.py` — AI endpoint tests (generate/analyze/predict/diagnose). `tests/test_investigations.py` — canned-checks tests. `tests/test_mongo_client.py` — asserts the Mongo client is constructed `tz_aware=True` (a real prior bug: BSON datetimes decode naive by default, which crashes arithmetic against `datetime.now(timezone.utc)` elsewhere in the scheduler). `tests/test_redis_acl_reconciliation.py` — the Redis ACL self-heal loop (below).
- `tests/acceptance/` — home-lab acceptance suite, opt-in (`HYDRA_ACCEPTANCE=1`, never runs in CI): stands up or points at a real deployment and checks domain isolation, the full executor matrix, mixed Python+Go worker-pool routing, and chaos/resilience (worker killed mid-job, Redis/Mongo restarted). Three backends (`docker` fully self-provisioning, `kubectl` verifies an already-Helm-installed deployment, `none` bare API smoke check) — see `tests/acceptance/README.md`. Run via `./scripts/run-acceptance-tests.sh`.

## Building and Running

The project relies heavily on Docker Compose for orchestration.

### Prerequisites

*   Docker
*   Docker Compose
*   Git (for local development)

### Quick Start (Full Stack)

To start the scheduler, worker, UI, Redis, and MongoDB:

```bash
# Using the helper script (recommended for dev)
./scripts/dev-up.sh

# OR using docker-compose directly
ADMIN_TOKEN=admin_secret GEMINI_API_KEY=<your_key> OPENAI_API_KEY=<your_key> docker compose up --build
```

The services will be available at:
*   **UI:** http://localhost:5173
*   **Scheduler API:** http://localhost:8000
*   **Redis:** localhost:6379
*   **MongoDB:** localhost:27017

### Running a Worker Separately

Workers can be run independently to scale processing power.

```bash
API_TOKEN=<domain_token> DOMAIN=prod \
REDIS_URL=redis://localhost:6379/0 REDIS_PASSWORD=<acl_password> \
docker compose -f docker-compose.worker.yml up --build

# Scale workers (WORKER_ID defaults to auto-generated unique IDs)
API_TOKEN=<domain_token> DOMAIN=prod \
docker compose -f docker-compose.worker.yml up --build --scale worker=2

# Go worker variant
API_TOKEN=<domain_token> DOMAIN=prod \
REDIS_URL=redis://localhost:6379/0 REDIS_PASSWORD=<acl_password> \
docker compose -f docker-compose.worker.go.yml up --build

# Scale Go workers
API_TOKEN=<domain_token> DOMAIN=prod \
docker compose -f docker-compose.worker.go.yml up --build --scale go-worker=2
```

### Development Servers

For local development without Docker:

- Scheduler: `uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000`
- UI: `npm install && npm run dev` inside `ui/` (set `VITE_API_BASE_URL`)

### Helper Scripts

Located in `scripts/`:
*   `dev-up.sh`: Starts the development stack.
*   `dev-down.sh`: Stops the development stack.
*   `test.sh`: Runs Python backend tests.
*   `test-all.sh`: Runs all tests.
*   `worker-up.sh`: Starts a single worker pool against an existing scheduler; `WORKER_FLAVOR=python` (default) or `WORKER_FLAVOR=go` picks `docker-compose.worker.yml` vs `docker-compose.worker.go.yml`.
*   `build-images.sh`: Builds Docker images.
*   `create-domain.sh`: Creates a new domain via the API.
*   `provision-redis-acl.sh`: Rotates/provisions domain worker Redis ACL credentials via admin API.
*   `configure-external-redis-acl.sh`: Configures domain worker ACL user directly on an external Redis server via `redis-cli`.
*   `start-domain-workers.sh`: Agentic worker bring-up for Docker/Kubernetes/Bare deployments; `WORKER_FLAVOR=python|go` selects the compose file for `WORKER_BACKEND=docker`.
*   `diagnose-domain-admin.sh`: Agentic diagnostics for domain auth and worker visibility (with optional Redis deep checks).
*   `hydra-apply.py`: Applies a job definition (YAML/JSON) via the API — used by `hydra-ctl apply`.
*   `run-acceptance-tests.sh`: Runs the home-lab acceptance suite (`tests/acceptance/`) against an already-running deployment (Docker Compose, live Kubernetes/Helm, or a bare API endpoint).

The Compose files themselves (`docker-compose.worker.go.yml`, `docker-compose.workers.yml`, etc.) live at the repo root, not in `scripts/` — see the "Docker Deployment" section of `README.md` for the full set and how they combine.

## Testing

### Backend (Python)

*   Uses `pytest` for testing.
*   Install dependencies: `uv sync --dev`
*   Run tests: `./scripts/test.sh` or `uv run pytest tests/`
*   Specific tests: `uv run pytest tests/test_scheduler.py tests/test_worker.py`
*   Test files located in `tests/`
*   Note: The end-to-end test is skipped unless the full stack is running.
*   Home-lab acceptance suite (`tests/acceptance/`) is separate from all of the above — opt-in, minutes not seconds, never runs in CI. `./scripts/run-acceptance-tests.sh` or `HYDRA_ACCEPTANCE=1 uv run pytest tests/acceptance -v`. See `tests/acceptance/README.md`.

### Operator CLI

*   Run `uv run hydra-ctl --help` for the resource-oriented API client.
*   Configure it with `HYDRA_API_URL`, `HYDRA_TOKEN`, and `HYDRA_DOMAIN`; the
    token and domain also fall back to the worker-compatible `API_TOKEN` and
    `DOMAIN` variables.

### Frontend (React)

*   Uses `vitest` for testing.
*   Run tests: `cd ui && npm test`
*   Cypress integration tests: `cd ui && npm run cypress:open` or `cd ui && npm run cypress:run` (expects UI running on `http://localhost:5173`)

## Configuration Notes

### Common Environment Variables

- `REDIS_URL` — Redis connection URL
- `REDIS_SENTINELS` — Comma-separated Sentinel hosts (`host1:26379,host2:26379`)
- `REDIS_SENTINEL_MASTER` — Sentinel master name (e.g. `mymaster`)
- `REDIS_DB` — Redis DB index for Sentinel mode (default `0`)
- `REDIS_SOCKET_TIMEOUT` — Redis/Sentinel socket timeout seconds (default `2`)
- `REDIS_USERNAME` / `REDIS_PASSWORD` — Redis auth for master connection
- `REDIS_SENTINEL_USERNAME` / `REDIS_SENTINEL_PASSWORD` — Optional Sentinel auth
- `MONGO_URL` — MongoDB connection URL
- `MONGO_DB` — MongoDB database name
- `SCHEDULER_HEARTBEAT_TTL` — Heartbeat TTL for workers
- `SCHEDULER_WORKER_OFFLINE_PRUNE_SECONDS` — Age threshold to prune stale offline worker registry records (default `1800`; minimum effectively `3 * SCHEDULER_HEARTBEAT_TTL`)
- `SCHEDULER_STARVATION_WARN_THRESHOLD` — Number of no-worker misses before logging a starvation warning for a pending job (default `5`)
- `SCHEDULER_BYPASS_MAX_EXTRA` — Maximum bypass_concurrency jobs per worker above its `max_concurrency` limit; `0` = unlimited (default `0`)
- `SCHEDULER_ACL_RECONCILE_INTERVAL` — Seconds between passes of the Redis ACL reconciliation loop, which re-applies persisted worker ACL users so a Redis-only restart self-heals (default `30`)
- `CORS_ALLOW_ORIGINS` — CORS allowed origins
- `ADMIN_TOKEN` — Admin authentication token
- `ADMIN_DOMAIN` — Admin domain name
- `GEMINI_API_KEY` — Google Gemini API key for AI features
- `OPENAI_API_KEY` — OpenAI API key for AI features
- `LOG_LEVEL` — Logging level

### Worker Environment Variables

- `DOMAIN` — Domain the worker belongs to
- `API_TOKEN` — Authentication token for the worker
- `REDIS_PASSWORD` — Domain-scoped worker Redis ACL password (Redis username is derived from `DOMAIN`)
- `WORKER_ID` — Unique worker identifier
- `WORKER_TAGS` — Tags for worker affinity
- `ALLOWED_USERS` — Users allowed to submit jobs to this worker
- `MAX_CONCURRENCY` — Maximum concurrent jobs
- `WORKER_STATE` — Initial worker state
- `DEPLOYMENT_TYPE` — Type of deployment. Auto-detected if not set: `docker` (Linux inside a Docker container), `scheduler` (set automatically by the Windows bootstrap watchdog), `standalone` (bare-OS process, not containerised and not managed by Task Scheduler). Override to `kubernetes` or other values as needed.
- `WORKER_METRICS_SAMPLE_SECONDS` — sampling interval for worker metrics history (default `15`)
- `WORKER_METRICS_WINDOW_SECONDS` — rolling metrics retention window in seconds (default `1800`)

### Additional Notes

- Python CI (`.github/workflows/python-ci.yml`) covers 3.11 and 3.13 across Linux, macOS, and Windows, plus separate jobs for lint (ruff), the Go worker (`go test ./...`), the Helm chart (`helm lint --strict` + `helm template` in three configurations), Docker image builds (scheduler/worker/go-worker/ui), a full-stack Compose smoke test (`tests/test_end_to_end.py`), and a Cypress browser journey. Python container images use 3.13 slim and install the locked environment with `uv`.
- A separate `.github/workflows/release-please.yml` runs on every push to `main`, driving automatic versioning/changelog/GitHub Releases from commit messages — see the commit-message rule under **Working Agreements** below and `CONTRIBUTING.md`.
- Environment variables can be configured via `.env` file (see `.env.example`).
- MongoDB uses a named volume `mongo-data` for persistence.
- Redis connection precedence: if both `REDIS_SENTINELS` and `REDIS_SENTINEL_MASTER` are set, scheduler/worker use Sentinel discovery; otherwise they use `REDIS_URL`.

## AI Features

*   **Magic Job Generator:** In the UI "New Job" form, use natural language to generate job JSON. Select between Gemini and OpenAI from the dropdown.
*   **AI Log Assistant:** In Run Logs, use AI helper actions for remediation, summary, error extraction, retry tuning, or custom questions. Select between Gemini and OpenAI.
*   **Duration Prediction:** `POST /ai/predict_duration` — historical median/mean/p90 runtime for a job, no LLM call.
*   **Run Diff Copilot:** In Run Logs, "Compare vs Last Success" (`POST /ai/diagnose_regression`) diffs the failed run's output against the job's last successful run plus its duration baseline, returning a structured cause/confidence/evidence/fix/transience verdict instead of analyzing one run in isolation.
*   **Investigate (not AI):** header button opening canned, LLM-free checks (`GET /investigations/`) — recently failed, running longer than usual, flaky, never succeeded. No provider key required; complements the AI features above rather than replacing them.
*   **Configuration:** Ensure `GEMINI_API_KEY` and/or `OPENAI_API_KEY` are set in the Scheduler environment for the AI-backed features (not needed for Investigate).

## Git Source Execution

Jobs can now specify a git repository as a source.

```json
{
  "source": {
    "url": "https://github.com/user/repo.git",
    "ref": "main",
    "path": "scripts"
  },
  "executor": { "type": "shell", "script": "./run.sh" }
}
```

The worker will clone the repo to a temporary directory, switch to `path` (if provided), and execute the script within that context.

## Development Conventions

### Backend (Python)

*   **Location:** `scheduler/` and `worker/`
*   **Style:** Adheres to standard Python 3.13 practices. Type hints are encouraged. All datetime values use timezone-aware UTC (`datetime.now(timezone.utc)`).
*   **Linting:** Run `uv run ruff check .`; match existing 4-space indentation and type-hint style.

### Frontend (React)

*   **Location:** `ui/`
*   **Stack:** React, TypeScript, Vite, Ant Design.
*   **Linting:** Standard Vite/React configurations.

## Known Gaps / Cleanup Targets

- Queue-based routing is not implemented; all dispatching is per worker/domain. If queues are needed, add scheduler-side selection rules and worker registration metadata accordingly.

## Working Agreements

- Commit after each meaningful change with a clear description of what changed and why. Keep commits small and scoped.
- **Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/)** — `<type>[optional scope]: <description>`, e.g. `fix: correct duration calc when a run has no start_ts` or `feat(worker): add heartbeat liveness file for Go workers`. This isn't just style: `.github/workflows/release-please.yml` parses these on every push to `main` to drive automatic version bumps (`pyproject.toml`, `ui/package.json`, `deploy/helm/hydra/Chart.yaml`), `CHANGELOG.md` generation, and GitHub Releases — a non-conventional commit is silently invisible to that pipeline (no version bump, no changelog line). Types that matter: `fix:` (patch), `feat:` (minor — this repo is pre-1.0 with `bump-minor-pre-major: true`), `fix!:`/`feat!:`/a `BREAKING CHANGE:` footer (major), `perf:` (patch); `docs:`/`chore:`/`refactor:`/`test:`/`build:`/`ci:` don't bump the version or show in the changelog. **This repo merges PRs with a merge commit (not squash)**, so each individual commit reaching `main` is scanned on its own — write every commit message as if it stands alone, not just the PR title. Full details and examples: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Use `git status`/`git diff` frequently before committing to keep the working tree clean and to avoid drifting config or lockfiles.
- When editing, align affinity/capability expectations across scheduler, worker, and UI to prevent drift between enforcement and presentation.
- Keep `AGENTS.md` current whenever architecture, APIs, auth behavior, deployment workflow, or operator-facing features change.
