# hydra-jobs

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![MongoDB](https://img.shields.io/badge/MongoDB-6-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)

**Hydra Jobs** is a production-ready distributed job scheduler and runner built for flexibility, multi-tenancy, and scale. It ships a full stack: a FastAPI scheduler, cross-platform Python workers, and a React UI — all wired through Redis and MongoDB.

---

## ✨ Key Features

| Category | Capabilities |
|---|---|
| **Executors** | `shell`, `python`, `batch`, `powershell`, `sql` (Postgres/MySQL/MSSQL/Oracle/MongoDB), `http` (REST/webhooks), `external` |
| **Scheduling** | Immediate, cron (with timezone), interval — with optional `start_at`/`end_at` windows |
| **Source Provisioning** | Git clone (PAT auth, sparse checkout), local `copy`, SSH `rsync` |
| **AI Assistance** | Natural-language job generation + run failure analysis via Google Gemini or OpenAI |
| **Multi-Domain** | Full tenant isolation with per-domain tokens and Redis ACL scoping |
| **Affinity** | Route jobs by OS, tags, hostnames, subnets, deployment type, or executor capability |
| **Reliability** | Retries with delay, timeout enforcement, failover requeue, dependency graph (`depends_on`) |
| **Alerting** | On-failure webhooks and SMTP email alerts (domain-scoped credentials) |
| **Security** | Domain-scoped tokens, encrypted credential store, per-domain Redis ACL, Linux user impersonation, Kerberos pre-auth |
| **Observability** | Real-time SSE log streaming, Gantt/concurrency timeline, worker metrics trends, operational event history |
| **Deployment** | Docker Compose, Kubernetes manifests, Redis Sentinel HA |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           Scheduler (FastAPI)                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────────┐ │
│  │ Schedule     │  │  Dispatch /      │  │  Run Event Loop            │ │
│  │ Trigger Loop │  │  Failover Loop   │  │  (Redis run_events →       │ │
│  │              │  │                  │  │   MongoDB job_runs)        │ │
│  └──────────────┘  └──────────────────┘  └────────────────────────────┘ │
└────────────┬─────────────────┬────────────────────────────────┬──────────┘
             │ dispatch/queues │ worker state / run_events      │ read/write
             ▼                 ▼                                ▼
      ┌─────────────────────────────┐                  ┌───────────┐
      │            Redis            │                  │  MongoDB  │
      │  (queues, heartbeats,       │                  │  (domains,│
      │   logs, events, ACL)        │                  │   jobs,   │
      └──────────┬──────────────────┘                  │   runs,   │
                 │ dispatch / heartbeat                 │   creds)  │
                 │ / logs / events                      └───────────┘
     ┌───────────┼───────────────────┐
     ▼           ▼                   ▼
┌─────────┐ ┌─────────┐       ┌─────────┐
│ Worker  │ │ Worker  │       │ Worker  │
│(domainA)│ │(domainA)│       │(domainB)│
└─────────┘ └─────────┘       └─────────┘
```

- **Scheduler** owns orchestration and persistence: dispatches jobs to Redis queues, handles failover, advances cron/interval schedules, and persists run events consumed from Redis into MongoDB.
- **Workers** are Redis-only at runtime: register metadata, heartbeat with rolling metrics (memory/CPU/load), execute jobs, stream logs, and emit lifecycle events — they never connect to MongoDB.
- **MongoDB** stores durable state: `domains`, `job_definitions`, `job_runs`, `credentials`.

> See [`docs/architecture.md`](docs/architecture.md) for a detailed Mermaid diagram.

---

## Quick Start

**Prerequisites:** Docker + Docker Compose

```bash
ADMIN_TOKEN=my_secret docker compose up --build
```

| Service | Address |
|---|---|
| UI | http://localhost:5173 |
| Scheduler API | http://localhost:8000 |
| Redis | localhost:6379 |
| MongoDB | localhost:27017 |

> Set `GEMINI_API_KEY` or `OPENAI_API_KEY` to enable AI features.

---

## Executors

Jobs declare an `executor` block to choose how they run:

```jsonc
// Shell
{ "type": "shell", "script": "echo hello", "shell": "bash" }

// Python (with isolated venv)
{ "type": "python", "code": "print('hi')", "environment": { "type": "venv", "requirements": ["requests"] } }

// SQL (with row limits and transaction control)
{ "type": "sql", "dialect": "postgres", "credential_ref": "my-db", "query": "SELECT 1", "max_rows": 10000, "autocommit": true }

// HTTP (REST triggers, webhooks, health checks)
{ "type": "http", "method": "POST", "url": "https://api.example.com/trigger", "headers": {"Content-Type": "application/json"}, "body": "{\"key\": \"value\"}", "expected_status": [200, 201] }

// PowerShell (Windows workers)
{ "type": "powershell", "script": "Get-Date" }
```

All executor types support `env`, `args`, `workdir`, `impersonate_user` (Linux/macOS), and Kerberos pre-auth.

### Workspace Caching

Source workspaces are cached per-worker to avoid repeated git clones and file copies. Configure via:

| Variable | Default | Description |
|---|---|---|
| `WORKER_WORKSPACE_CACHE_DIR` | OS temp dir | Cache root directory |
| `WORKER_WORKSPACE_CACHE_MAX_MB` | `1024` | Max total cache size (MB) |
| `WORKER_WORKSPACE_CACHE_TTL` | `3600` | Cache entry TTL (seconds) |
| `WORKER_WORKSPACE_CACHE_PERSIST` | `true` | Keep cache across restarts |

Per-job cache control via `source.cache`: `"auto"` (default), `"always"`, `"never"`.

### Non-Containerized Execution

When running workers outside Docker (bare-metal, VMs, or custom environments), the
following environment variables let you override paths that are normally guaranteed
by the container image:

| Variable | Default | Description |
|---|---|---|
| `HYDRA_PYTHON_PATH` | `python3` (PATH lookup) | Full path to Python interpreter for `python`/`sql` executors |
| `HYDRA_SHELL_PATH` | `/bin/bash` | Full path to bash for `shell` executor |
| `HYDRA_GIT_PATH` | `git` (PATH lookup) | Full path to git binary for source provisioning |
| `HYDRA_TEMP_DIR` | OS default (`/tmp`) | Scratch directory for executor temp files |

These apply to both the Python and Go workers.  When unset, all paths fall back to
the defaults used inside the Docker container image.

---

## Scheduling

```jsonc
// Run once immediately
{ "mode": "immediate" }

// Cron with timezone
{ "mode": "cron", "cron": "0 9 * * 1-5", "timezone": "America/New_York" }

// Every 30 minutes within a window
{ "mode": "interval", "interval_seconds": 1800, "start_at": "2025-01-01T00:00:00Z", "end_at": "2025-12-31T23:59:59Z" }
```

---

## Source Provisioning

Pull code at runtime before execution — no pre-baked images required:

```jsonc
// Git clone (PAT via stored credential)
{ "protocol": "git", "url": "https://github.com/org/repo.git", "ref": "main", "path": "scripts", "sparse": true, "credential_ref": "gh-pat" }

// Local filesystem copy
{ "protocol": "copy", "url": "/opt/jobs/my-script" }

// SSH rsync from remote host
{ "protocol": "rsync", "url": "deploy@build-server:/releases/latest" }
```

---

## AI Features

### Magic Job Generator
In the UI **New Job** form, describe a job in plain English and get a complete JSON definition — choose between Gemini and OpenAI.

### AI Log Assistant
On any run's log view, pick an analysis mode:
- **Failure Fix** — root-cause and remediation steps
- **Summary** — plain-language run summary
- **Error Extraction** — structured list of errors/warnings
- **Retry Tuning** — recommended retry/timeout settings
- **Custom Question** — ask anything about the logs

### Duration Prediction
`POST /ai/predict_duration` estimates expected runtime from historical run data (median, mean, p90).

---

## Multi-Domain & Security

Hydra Jobs is built for multi-tenant deployments. Each domain is fully isolated:

- **Domain token** (`x-api-key`) required for all non-admin API calls
- **Admin token** (`ADMIN_TOKEN`) grants cross-domain access
- **Redis ACL** per domain: workers are scoped to only their domain's keys and channels
- **Encrypted credential store**: database URIs, PAT tokens, SMTP passwords — all stored encrypted in MongoDB, resolved at dispatch, never returned by the API
- **Linux impersonation**: `executor.impersonate_user` runs jobs as a specific OS user
- **Kerberos**: `executor.kerberos` bootstraps a Kerberos ticket before execution; credential cache is destroyed immediately after the job completes
- **Secret masking**: `connection_uri` and `kerberos.keytab` path are redacted in all job API responses
- **Git PAT hygiene**: personal access tokens are injected only for the clone operation; the remote URL is rewritten to remove credentials before the workspace is cached
- **Secure temp files**: SQL driver scripts are written to mode `0o600` files so connection strings are never world-readable

### Start Workers (Recommended ACL Path)

```bash
# 1. Rotate domain token + worker Redis ACL credentials from Admin UI or:
#    POST /admin/domains/{domain}/redis_acl/rotate

# 2. Launch workers
API_TOKEN=<domain_token> \
DOMAIN=prod \
WORKER_REQUIRE_REDIS_ACL=true \
REDIS_URL=redis://localhost:6379/0 \
REDIS_PASSWORD=<worker_redis_acl_password> \
docker compose -f docker-compose.worker.yml up --build --scale worker=2
```

### Windows Workers — Task Scheduler Bootstrap

On Windows hosts, use the built-in bootstrap module to register a single Task
Scheduler task that keeps a Hydra worker alive:

```powershell
# Validate config first
$env:DOMAIN="prod"; $env:API_TOKEN="<token>"; $env:REDIS_URL="redis://host:6379/0"
python -m worker bootstrap validate

# Install the scheduled task (requires admin)
python -m worker bootstrap install

# Start the watchdog immediately (without waiting for reboot)
python -m worker bootstrap run

# Remove the task
python -m worker bootstrap remove
```

See [`docs/windows-worker-bootstrap.md`](docs/windows-worker-bootstrap.md) for a complete guide.

---

## Affinity & Routing

Target specific workers using the `affinity` block:

```jsonc
{
  "affinity": {
    "os": ["linux"],
    "tags": ["gpu", "high-mem"],
    "hostnames": ["worker-01"],
    "executor_types": ["python"],
    "deployment_types": ["docker", "scheduler"]
  }
}
```

---

## Reliability

- **Retries** with configurable delay: `max_retries`, `retry_delay_seconds`
- **Timeout** enforcement per job
- **Concurrency control**: `MAX_CONCURRENCY` per worker; `bypass_concurrency` for priority jobs
- **Failover**: scheduler requeues jobs from offline workers automatically
- **Dependency graph**: `depends_on` list; `GET /jobs/{job_id}/graph` returns full upstream/downstream graph
- **Completion criteria**: match on exit codes, stdout/stderr contains/not-contains

---

## Alerts & Webhooks

On terminal job failure:
```jsonc
{
  "on_failure_webhooks": ["https://hooks.example.com/notify"],
  "on_failure_email_to": ["ops@example.com"],
  "on_failure_email_credential_ref": "smtp-creds"
}
```

---

## API Reference

| Group | Endpoints |
|---|---|
| **Jobs** | `GET /jobs/` · `POST /jobs/` · `PUT /jobs/{id}` · `POST /jobs/{id}/run` · `POST /jobs/adhoc` · `POST /jobs/validate` · `GET /jobs/{id}/graph` |
| **Runs & Logs** | `GET /jobs/{id}/runs` · `GET /runs/{id}` · `GET /runs/{id}/stream` (SSE) · `GET /history` |
| **Workers** | `GET /workers/` · `GET /workers/{id}/metrics` · `GET /workers/{id}/timeline` · `GET /workers/{id}/operations` · `POST /workers/{id}/state` |
| **AI** | `POST /ai/generate` · `POST /ai/analyze` · `POST /ai/predict_duration` |
| **Domain Self-Service** | `GET /domain/settings` · `PUT /domain/settings` · `POST /domain/token/rotate` · `POST /domain/redis_acl/rotate` |
| **Credentials** | `GET /credentials/` · `POST /credentials/` · `PUT /credentials/{name}` · `DELETE /credentials/{name}` |
| **Admin** | `GET /admin/domains` · `POST /admin/domains` · `POST /admin/domains/{domain}/token` · `POST /admin/domains/{domain}/redis_acl/rotate` |

---

## High Availability: Redis Sentinel

```bash
REDIS_SENTINELS=host1:26379,host2:26379
REDIS_SENTINEL_MASTER=mymaster
# Optional
REDIS_SENTINEL_USERNAME=...
REDIS_SENTINEL_PASSWORD=...
```

If Sentinel vars are not set, `REDIS_URL` is used.

---

## Kubernetes

Manifests are in `deploy/k8s/`:
- `scheduler-deployment.yaml`
- `worker-deployment.yaml`
- `worker-job-template.yaml`
- `hydra.yaml` (full stack)

---

## Operator Scripts

| Script | Purpose |
|---|---|
| `scripts/dev-up.sh` | Start full dev stack |
| `scripts/provision-redis-acl.sh` | Provision domain worker ACL via scheduler API |
| `scripts/configure-external-redis-acl.sh` | Configure ACL on an external Redis directly |
| `scripts/start-domain-workers.sh <domain> [scale]` | Agentic worker bring-up (Docker/K8s/Bare) |
| `scripts/diagnose-domain-admin.sh <domain>` | Agentic domain + Redis diagnostics |
| `scripts/create-domain.sh` | Create a new domain via the API |

---

## Command-Line Interface (`hydra-ctl`)

`hydra-ctl` is a standalone CLI for interacting with the Hydra scheduler — think `gh` for Hydra. Install it on any machine that can reach the scheduler; it does not run jobs and has no dependency on Redis.

```bash
pip install hydra-jobs   # hydra-ctl is included
```

Authenticate via environment variables (same token the worker uses):

```bash
export API_TOKEN=<domain-token>
export DOMAIN=prod                          # default: prod
export HYDRA_API_URL=http://localhost:8000  # default: http://localhost:8000
```

Or pass flags directly:

```bash
hydra-ctl --token <TOKEN> --domain prod --api-url http://scheduler:8000 jobs list
```

### Commands

| Command | Description |
|---|---|
| `jobs list [--search TEXT] [--tags t1,t2]` | List jobs with schedule mode and last-run status |
| `jobs show <name-or-id>` | Full job definition |
| `jobs trigger <name-or-id> [--param k=v …]` | Manually trigger a job; prints run ID |
| `jobs enable <name-or-id>` | Enable schedule |
| `jobs disable <name-or-id>` | Disable schedule |
| `jobs runs <name-or-id> [--limit N]` | Run history for a job |
| `runs list [--limit N]` | Recent runs across all jobs |
| `runs show <run-id>` | Run metadata and outcome |
| `runs logs <run-id>` | Print logs (streams live if run is active) |
| `runs kill <run-id>` | Kill an active run |
| `workers list` | Worker list with state and running-job count |
| `workers show <worker-id>` | Worker detail (capabilities, tags, metrics) |
| `workers state <worker-id> online\|draining\|offline` | Change worker dispatch state |
| `overview` | Domain summary: job totals, success rate, active workers |
| `overview queue [--limit N]` | Pending + upcoming scheduled jobs |

Add `--json` to any command for machine-readable output.

---

## Worker Status

| Dimension | Values |
|---|---|
| `connectivity_status` | `online` \| `offline` (heartbeat-derived) |
| `dispatch_status` | `online` \| `draining` \| `offline` (operator-controlled) |

`POST /workers/{id}/state` accepts `online`, `draining`, `offline` (`disabled` accepted as legacy alias).

---

## UI Highlights

- **Login gate**: unauthenticated users see only the auth screen
- **Operate view**: live job list with inline run/edit/delete
- **Observe view**: run history and real-time status
- **Worker detail**: metrics trends, concurrency Gantt timeline, operational event history
- **Log viewer**: search/highlight, parsed/raw toggle, expand, copy
- **AI assistant**: integrated in log view and job creation form
- **Dark/light mode** persistent toggle
- **Admin panel**: domain management, credential CRUD, token rotation

---

## Development

```bash
# Scheduler (hot-reload)
uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# UI (Vite dev server)
cd ui && npm install && npm run dev

# Backend tests
python -m pytest tests/ --ignore=tests/test_end_to_end.py -v

# UI unit tests
cd ui && npx vitest run

# Cypress e2e (requires UI running)
cd ui && npm run cypress:open   # interactive
cd ui && npm run cypress:run    # headless
```

See also: [`docs/README.md`](docs/README.md), [`docs/development/docker-compose-workflows.md`](docs/development/docker-compose-workflows.md), [`docs/development/testing.md`](docs/development/testing.md)

---

## Troubleshooting

- **CORS errors**: set `CORS_ALLOW_ORIGINS` (comma-separated or `*`); ensure scheduler is reachable from the UI host.
- **Worker unauthorized/offline**: verify `DOMAIN` + `API_TOKEN`; re-rotate domain token if invalidated; verify `REDIS_PASSWORD` if ACL is required.
- **Storage pressure**: low disk can corrupt MongoDB startup — recover space before restarting, check `docker system df`.

---

## Redis Key Layout

```
job_queue:<domain>:pending
job_queue:<domain>:<worker_id>
workers:<domain>:<worker_id>
worker_heartbeats:<domain>
worker_running_set:<domain>:<worker_id>
job_running:<domain>:<job_id>
worker_metrics:<domain>:<worker_id>:history
run_events:<domain>
worker_ops:<domain>:<worker_id>
log_stream:<domain>:<run_id>*
```

---

## License

[MIT](LICENSE)
