# Hydra Jobs — Architecture

## Component Overview

| Component | Role |
|---|---|
| **Scheduler API** | FastAPI service: REST API + SSE streams. In `api` mode: API only. In `combined` mode (default): API + orchestration loops. Startup/shutdown managed via FastAPI `lifespan` context manager. |
| **Orchestrator** | Control-plane process: owns all background reconciliation loops (dispatch, failover, schedule, events, monitoring). Can run as a separate process (`python -m scheduler.orchestrator_entrypoint`) or co-located with the API in `combined` mode. |
| **Redis** | Message bus: job queues, worker coordination, heartbeats, log streaming, run events |
| **MongoDB** | Durable store: domains, job definitions, run history, credentials |
| **Workers** | Execution agents: Redis-only at runtime — receive jobs, run them, emit events. Available in Python and Go with feature parity. |
| **UI** | React frontend: monitors jobs/workers/runs via scheduler REST API and SSE |

## Runtime Modes

### Combined mode (default)

Both the API service and all orchestration loops run inside the same process. This is the default for simplicity, local development, and small deployments.

```
HYDRA_MODE=combined  (or unset)
```

Start with the standard Compose file:

```bash
docker compose up --build
```

### Separated mode

The API service and control-plane orchestrator run as separate processes. This gives independent fault domains, restartability, and observability per role.

```
HYDRA_MODE=api          # on the scheduler container
HYDRA_MODE=orchestrator # on the orchestrator container (informational)
```

Start with the separated override:

```bash
docker compose -f docker-compose.yml -f docker-compose.separated.yml up --build
```

### Process ownership summary

| Responsibility | Combined | API process | Orchestrator process |
|---|:---:|:---:|:---:|
| REST API + SSE | ✓ | ✓ | — |
| Schedule advancement (cron/interval) | ✓ | — | ✓ |
| Job dispatch to workers | ✓ | — | ✓ |
| Worker failover + queue drain | ✓ | — | ✓ |
| Run event ingestion (Redis → MongoDB) | ✓ | — | ✓ |
| Timeout enforcement | ✓ | — | ✓ |
| SLA monitoring | ✓ | — | ✓ |
| Backfill dispatch | ✓ | — | ✓ |
| Orchestrator heartbeat | ✓ | — | ✓ |

## Architecture Diagram

```mermaid
flowchart TB
    UI["React UI\n(Vite + Ant Design)"]

    subgraph APIService["Scheduler API (FastAPI)"]
        API["REST API\n+ SSE streams"]
    end

    subgraph ControlPlane["Orchestrator (control-plane)"]
        STL["Schedule Trigger Loop\n(cron / interval → dispatch)"]
        DFL["Dispatch Loop\n(pending queue → worker queues)"]
        FOL["Failover Loop\n(offline workers → requeue)"]
        REL["Run Event Loop\n(run_events → MongoDB)"]
        MON["Timeout · SLA · Backfill\nMonitors"]
        HB["Orchestrator Heartbeat\n(hydra:orchestrator:heartbeat)"]
    end

    subgraph Stores["Data Stores"]
        Redis[("Redis 7\n· job queues\n· heartbeats\n· log streams\n· run events\n· worker ops\n· ACL")]
        MongoDB[("MongoDB 6\n· domains\n· job_definitions\n· job_runs\n· credentials")]
    end

    subgraph WorkerPool["Workers (Redis-only at runtime)"]
        WA1["Python Worker\n(domain-a)"]
        WA2["Python Worker\n(domain-a)"]
        WB1["Go Worker\n(domain-b)"]
    end

    %% Clients ↔ Scheduler API
    UI  -- "HTTP / SSE" --> API
    API -- "read / write" --> MongoDB

    %% Orchestrator loops ↔ Redis + MongoDB
    STL -- "advance schedule" --> MongoDB
    STL -- "enqueue pending" --> Redis
    DFL -- "read worker state\n+ pending queue" --> Redis
    DFL -- "resolve credential_refs" --> MongoDB
    DFL -- "dispatch → worker queue" --> Redis
    FOL -- "detect stale heartbeats" --> Redis
    FOL -- "mark failed runs" --> MongoDB
    REL -- "consume run_events\n(RPOPLPUSH staging)" --> Redis
    REL -- "persist job_runs" --> MongoDB
    MON -- "timeout / SLA / backfill" --> MongoDB
    HB  -- "heartbeat key (TTL=30s)" --> Redis

    %% Redis ↔ Workers
    Redis -- "BLPOP job dispatch" --> WA1
    Redis -- "BLPOP job dispatch" --> WA2
    Redis -- "BLPOP job dispatch" --> WB1

    WA1 -- "heartbeat · metrics\nlogs · run events · ops" --> Redis
    WA2 -- "heartbeat · metrics\nlogs · run events · ops" --> Redis
    WB1 -- "heartbeat · metrics\nlogs · run events · ops" --> Redis
```

> **Note:** In `combined` mode (default) both `Scheduler API` and `Orchestrator` run in the same OS process. In `separated` mode they are distinct processes (or containers) connected only through Redis and MongoDB.

## Job Dispatch Sequence

The following sequence diagram shows the full lifecycle of a scheduled job — from trigger through execution to persistence.

```mermaid
sequenceDiagram
    participant STL as Schedule Trigger Loop
    participant DFL as Dispatch Loop
    participant Redis
    participant Worker
    participant REL as Run Event Loop
    participant MongoDB

    Note over STL,MongoDB: 1. Schedule advancement
    STL->>MongoDB: Read next_run_at for due jobs
    STL->>MongoDB: Update next_run_at (advance schedule)
    STL->>Redis: ZADD job_queue:<domain>:pending

    Note over DFL,MongoDB: 2. Dispatch
    DFL->>Redis: ZPOPMIN job_queue:<domain>:pending
    DFL->>Redis: Read workers:<domain>:* (affinity check)
    DFL->>MongoDB: Resolve credential_refs (decrypt)
    DFL->>Redis: RPUSH job_queue:<domain>:<worker_id>

    Note over Worker,Redis: 3. Execution
    Worker->>Redis: BLPOP job_queue:<domain>:<worker_id>
    Worker->>Redis: SET job_running:<domain>:<job_id>
    Worker->>Redis: SADD worker_running_set:<domain>:<worker_id>
    Worker->>Redis: RPUSH run_events:<domain> {run_start}
    Worker->>Redis: PUBLISH log_stream:<domain>:<run_id> (chunks)
    Worker->>Redis: RPUSH run_events:<domain> {run_end}
    Worker->>Redis: DEL job_running / SREM running_set

    Note over REL,MongoDB: 4. Event ingestion
    REL->>Redis: RPOPLPUSH run_events:<domain> → staging
    REL->>MongoDB: Upsert job_runs (run_start → $setOnInsert)
    REL->>MongoDB: Update job_runs terminal state (run_end)
    REL->>Redis: LREM staging queue
```

## Worker Deployment Options

Hydra workers are stateless and Redis-only. They can be deployed in several configurations:

```mermaid
flowchart LR
    subgraph DockerCompose["Docker Compose (local / small prod)"]
        direction TB
        W1["python worker"]
        W2["python worker"]
        W3["go worker"]
    end

    subgraph Kubernetes["Kubernetes"]
        direction TB
        W4["worker Pod"]
        W5["worker Pod"]
        W6["worker Pod (HPA)"]
    end

    subgraph Windows["Windows Bare-Metal"]
        direction TB
        BS["bootstrap watchdog\n(Task Scheduler OR\nWindows Service via NSSM)"]
        BS --> WW["python -m worker"]
    end

    subgraph BareMetal["Linux / macOS Bare-Metal"]
        direction TB
        WL["python -m worker\n(standalone)"]
    end

    Redis2[("Redis")]
    W1 & W2 & W3 --> Redis2
    W4 & W5 & W6 --> Redis2
    WW --> Redis2
    WL --> Redis2
```

## Multi-Domain Security Model

Each domain is a fully isolated tenant. The diagram below shows how tokens and Redis ACL rules are scoped per domain.

```mermaid
flowchart TB
    AdminToken["Admin Token\n(ADMIN_TOKEN env)"]

    subgraph DomainA["Domain: prod"]
        TokenA["Domain Token\n(hashed in MongoDB)"]
        ACLA["Redis ACL User: prod\n(scoped to prod:* keys)"]
        WorkerA1["Worker A1"]
        WorkerA2["Worker A2"]
    end

    subgraph DomainB["Domain: staging"]
        TokenB["Domain Token\n(hashed in MongoDB)"]
        ACLB["Redis ACL User: staging\n(scoped to staging:* keys)"]
        WorkerB1["Worker B1"]
    end

    subgraph Scheduler["Scheduler API"]
        AuthMiddleware["Auth Middleware\n(x-api-key header)"]
        CredStore["Encrypted Credential Store\n(AES-GCM in MongoDB)"]
    end

    AdminToken -- "cross-domain\naccess" --> AuthMiddleware
    TokenA -- "domain-scoped\naccess" --> AuthMiddleware
    TokenB -- "domain-scoped\naccess" --> AuthMiddleware

    AuthMiddleware --> CredStore

    ACLA --> WorkerA1
    ACLA --> WorkerA2
    ACLB --> WorkerB1

    WorkerA1 -. "can only read/write\nprod:* Redis keys" .-> ACLA
    WorkerB1 -. "can only read/write\nstaging:* Redis keys" .-> ACLB

    CredStore -. "decrypted at dispatch,\nnever stored on worker" .-> WorkerA1
    CredStore -. "decrypted at dispatch,\nnever stored on worker" .-> WorkerB1
```

## Failover Sequence

When a worker goes offline unexpectedly, the `failover_loop` recovers both in-flight running jobs and dispatched-but-not-started envelopes.

```mermaid
sequenceDiagram
    participant FOL as Failover Loop
    participant Redis
    participant MongoDB

    Note over FOL,Redis: Every 2 seconds
    FOL->>Redis: Read worker_heartbeats:<domain> (sorted set)
    FOL->>Redis: Check age vs SCHEDULER_HEARTBEAT_TTL

    alt Worker heartbeat is stale
        FOL->>Redis: SET NX worker_failover_handled:<domain>:<worker_id> (TTL guard)

        Note over FOL,MongoDB: Recover running jobs
        FOL->>Redis: SMEMBERS worker_running_set:<domain>:<worker_id>
        FOL->>MongoDB: Mark open run docs as failed (worker offline)
        FOL->>Redis: DEL job_running:<domain>:<job_id> (for each)

        Note over FOL,Redis: Recover dispatched-but-not-started envelopes
        FOL->>Redis: LRANGE job_queue:<domain>:<worker_id> (drain entire queue)
        FOL->>Redis: ZADD job_queue:<domain>:pending (re-enqueue each envelope)

        Note over FOL,Redis: Reset worker state
        FOL->>Redis: SET workers:<domain>:<worker_id> current_running=0, status=offline
    else Heartbeat is fresh
        Note over FOL: No action
    end

    Note over FOL,Redis: Stale worker pruning (after SCHEDULER_WORKER_OFFLINE_PRUNE_SECONDS)
    FOL->>Redis: DEL workers / heartbeat / running_set keys (if queues empty)
```

## Orchestration Health

The `OrchestratorManager` (owned by either the combined API process or the standalone orchestrator) writes a heartbeat key to Redis every 10 seconds:

```
hydra:orchestrator:heartbeat  →  {"ts": <unix timestamp>, "loops": ["scheduling", "failover", ...]}
```

The key has a 30-second TTL; if the process dies the key expires automatically.

To check orchestration health:

```bash
GET /health/orchestration
```

Example responses:

```json
{"status": "ok", "age_seconds": 3.2, "loops": ["scheduling", "failover", "schedule_trigger", "run_event", "timeout", "sla", "backfill"]}
{"status": "stale", "age_seconds": 45.1, "loops": [...]}
{"status": "unknown", "message": "No orchestrator heartbeat found. ..."}
```

This lets operators and monitoring systems independently verify:
- `GET /health` — API is up and can serve requests.
- `GET /health/orchestration` — Control-plane loops are running and healthy.

## Data Flow

### Job Submission & Dispatch
1. Client submits a job via `POST /jobs/` → scheduler validates and stores in **MongoDB**.
2. **Schedule Trigger Loop** fires when a cron/interval expression is due and enqueues a run into `job_queue:<domain>:pending` in **Redis**.
3. **Dispatch Loop** picks the best worker using affinity rules, resolves credential refs from **MongoDB**, and pushes the full job envelope to `job_queue:<domain>:<worker_id>` in **Redis**.
4. **Worker** BLPOPs its dedicated queue, executes the job, and streams logs to `log_stream:<domain>:<run_id>` in **Redis**.

### Run Lifecycle Events
5. Worker emits `run_start` and `run_end` events to `run_events:<domain>` in **Redis**.
6. **Run Event Loop** (in scheduler) atomically stages each event via `RPOPLPUSH`, processes it, then removes it from the staging queue.  Run documents are persisted to the `job_runs` collection in **MongoDB**.  See [Run Lifecycle](#run-lifecycle) for full state-transition and idempotency semantics.

### Worker Coordination (Redis-only)
- Workers write registration metadata and heartbeats to `workers:<domain>:<worker_id>` in **Redis**.
- Rolling metrics (memory, CPU, load) are stored in `worker_metrics:<domain>:<worker_id>:history` in **Redis**.
- Operational events (dispatches, state changes, failovers) are logged to `worker_ops:<domain>:<worker_id>` in **Redis**.
- Workers **never connect to MongoDB**.

## Job Run State Machine

Each job run moves through the following states. The transitions are explicit so operators and developers can reason about where a job is and what happened to it.

```mermaid
stateDiagram-v2
    [*] --> pending : cron/interval trigger\nor POST /jobs/{id}/run

    pending --> dispatched : dispatch loop finds\neligible worker
    pending --> pending    : no eligible worker\n(no_worker requeue)

    dispatched --> running   : worker BLPOP\n+ run_start event
    dispatched --> pending   : failover requeue\n(worker offline before BLPOP)

    running --> success   : run_end status=success
    running --> failed    : run_end status=failed
    running --> timed_out : timeout_seconds exceeded

    failed    --> pending : retry (new run_id)
    timed_out --> pending : retry (new run_id)

    success   --> [*]
    failed    --> [*]
    timed_out --> [*]

    note right of pending
        Redis: job_queue:<domain>:pending
        MongoDB: no run doc yet
    end note

    note right of dispatched
        Redis: job_queue:<domain>:<worker_id>
        MongoDB: no run doc yet
    end note

    note right of running
        Redis: job_running + worker_running_set
        MongoDB: status = running
    end note
```

### State definitions

| State | Redis keys present | MongoDB run status | How it ends |
|---|---|---|---|
| **pending** | `job_queue:<domain>:pending` entry | — (no run doc yet) | Worker found → dispatched; or removed |
| **dispatched** | `job_queue:<domain>:<worker_id>` envelope | — (no run doc yet) | Worker BLPOP → running; or failover → pending |
| **running** | `job_running:<domain>:<job_id>`, `worker_running_set` entry | `running` | Job completes/fails → success/failed/timed_out |
| **timed_out** | none (cleared on timeout kill) | `failed` (timeout) | Timeout enforcement sends kill signal |
| **orphaned / failover-eligible** | Running keys present, heartbeat expired | `running` → updated to `failed` on requeue | `failover_loop` detects heartbeat expiry → requeue |
| **requeued** | Back in `job_queue:<domain>:pending` | Prior run marked `failed` | Next dispatch cycle picks it up |

### Requeue metadata

Every job in the pending queue has an associated `job_enqueue_meta:<domain>:<job_id>` hash with:
- `enqueued_ts` — Unix timestamp when this queue entry was created.
- `reason` — Why this job entered (or re-entered) the queue: `immediate`, `schedule`, `retry`, `failover_requeue`, `no_worker`, `worker_detached`, etc.
- `retry_attempt` — Retry counter (incremented by the worker on retry).
- `no_worker_count` — How many times the dispatch loop has found no eligible worker for this job. Used for starvation detection and surfaced in queue/pressure APIs.

### No-worker starvation detection

When the dispatch loop pops a job from the pending queue but finds no eligible worker (no matching affinity, all workers at capacity, etc.), it:
1. Increments `no_worker_count` in the job's enqueue metadata.
2. Re-adds the job to the pending queue at its original priority.
3. Emits a `job_pending` event with `reason: "no_worker"` and the current `no_worker_count`.
4. Logs a **starvation warning** when `no_worker_count` reaches `SCHEDULER_STARVATION_WARN_THRESHOLD` (default: 5), and again at each subsequent multiple of that threshold.

Operators can observe starvation via:
- `GET /overview/queue` — each pending item includes `no_worker_count`.
- `GET /overview/pressure` — per-domain `stalled_count` and `max_no_worker_count`.
- Scheduler logs (warning level).

## Failover Semantics

### Trigger conditions
The `failover_loop` fires every 2 seconds. It calls `failover_once()` which scans all `worker_heartbeats:<domain>` sorted sets for workers whose last heartbeat is older than `SCHEDULER_HEARTBEAT_TTL` seconds.

### Failover actions
When a worker is detected offline:

1. **Running jobs** — jobs in `worker_running_set:<domain>:<worker_id>` had their `run_start` event emitted. Failover marks any open MongoDB run document as `failed` with `completion_reason: "worker offline; job requeued"`, clears the `job_running` key, and returns the job to the domain pending queue.

2. **Dispatched-but-not-started jobs** — envelopes in `job_queue:<domain>:<worker_id>` were pushed by the scheduler but not yet consumed by the worker. Failover drains the entire per-worker queue and returns these envelopes to the domain pending queue, preserving their original priority and retry state. Without this step, these jobs would be silently lost.

3. **Worker state** — the worker's `current_running` counter is reset to 0 and its status is set to `offline`.

### Duplicate-execution protection
A `worker_failover_handled:<domain>:<worker_id>` key (TTL = `max(10, ttl * 2)` seconds) prevents the failover loop from processing the same offline worker repeatedly within the TTL window. The key is set with `NX` (set-if-not-exists), so only the first observation triggers recovery.

### Stale worker pruning
If a worker has been offline for more than `SCHEDULER_WORKER_OFFLINE_PRUNE_SECONDS` (default: 1800s) *and* its running set and worker queue are both empty, the scheduler removes its registry keys from Redis. The operational timeline (`worker_ops`) is preserved for post-mortem inspection.

## Backpressure and Queue Visibility

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /overview/queue` | Domain-scoped pending queue items (first N, sorted by priority/enqueue time). Each item includes `no_worker_count` and the response includes `pending_total` per domain. |
| `GET /overview/pressure` | Per-domain backpressure summary: pending depth, stalled/starvation counts, per-worker dispatch queue depths, online worker count, total running vs capacity. |

### `GET /overview/pressure` fields

| Field | Description |
|---|---|
| `pending_total` | Total jobs in the domain pending queue (not page-limited). |
| `stalled_count` | Jobs with `no_worker_count ≥ starvation_threshold`. |
| `stalled_jobs` | Job IDs of stalled jobs. |
| `max_no_worker_count` | Highest `no_worker_count` across pending jobs. |
| `starvation_threshold` | Configured starvation threshold (`SCHEDULER_STARVATION_WARN_THRESHOLD`). |
| `worker_queue_depths` | Per-worker depth of dispatched-but-not-started queues. |
| `total_worker_queue_depth` | Sum of all per-worker queue depths. |
| `online_workers` | Number of workers currently heartbeating (state=online). |
| `total_running` | Sum of `current_running` across online workers. |
| `total_capacity` | Sum of `max_concurrency` across online workers. |

## `bypass_concurrency`

Jobs with `bypass_concurrency: true` skip the normal capacity check during worker selection. This is intended for time-critical or operational override jobs that must run immediately regardless of worker load.

### Guardrails and observability

- **Dispatch-time warning**: When a `bypass_concurrency` job is dispatched to a worker already at or above its normal `max_concurrency`, the scheduler logs a warning identifying the worker and its current load. This is logged at every bypass dispatch to an overloaded worker.

- **Configurable soft cap** (`SCHEDULER_BYPASS_MAX_EXTRA`, default: `0` = unlimited): When set to a positive integer, the scheduler filters out workers that already have more than that many bypass jobs running above their normal capacity. For example, `SCHEDULER_BYPASS_MAX_EXTRA=2` means no worker will receive more than 2 bypass jobs above its `max_concurrency`. If all workers exceed the cap, the job is requeued like a no-worker miss.

- **Dispatch operation log**: Every dispatch records `bypass_concurrency` in the `worker_ops` operational event, so the Gantt/timeline UI and operation history reflect bypass usage.

### Configuration

| Environment variable | Default | Description |
|---|---|---|
| `SCHEDULER_STARVATION_WARN_THRESHOLD` | `5` | Log a starvation warning after this many no-worker misses for a single job. |
| `SCHEDULER_BYPASS_MAX_EXTRA` | `0` (unlimited) | Maximum bypass jobs per worker above its normal concurrency cap. `0` disables the cap. |

## Redis Key Layout

| Key Pattern | Owner | Purpose |
|---|---|---|
| `job_queue:<domain>:pending` | Scheduler (write) / Scheduler (read) | Pending jobs waiting for dispatch (sorted set, score = priority) |
| `job_queue:<domain>:<worker_id>` | Scheduler (write) / Worker (read) | Per-worker dispatch queue (list of job envelopes) |
| `job_enqueue_meta:<domain>:<job_id>` | Scheduler | Metadata for each pending job: `enqueued_ts`, `reason`, `retry_attempt`, `no_worker_count` |
| `workers:<domain>:<worker_id>` | Worker | Registration metadata + heartbeat |
| `worker_heartbeats:<domain>` | Worker | Heartbeat timestamps (sorted set) |
| `worker_running_set:<domain>:<worker_id>` | Worker | Set of currently running job IDs |
| `job_running:<domain>:<job_id>` | Worker | Concurrency lock per job (run_id + heartbeat ts) |
| `worker_failover_handled:<domain>:<worker_id>` | Scheduler | Prevents repeated failover processing of the same offline worker within TTL window |
| `worker_metrics:<domain>:<worker_id>:history` | Worker | Rolling metrics history |
| `run_events:<domain>` | Worker (write) / Scheduler (read) | Run lifecycle event stream |
| `worker_ops:<domain>:<worker_id>` | Worker | Operational event log |
| `log_stream:<domain>:<run_id>*` | Worker | Real-time log chunks |

## Security Boundaries

- Each domain has its own **Redis ACL user** (username = domain name). Workers can only access keys and channels scoped to their domain.
- The scheduler's admin token grants cross-domain access; domain tokens scope all other requests.
- **Credentials** (DB URIs, PAT tokens, SMTP passwords) are encrypted in MongoDB and resolved at dispatch time by the scheduler. Workers receive them in the job envelope — they are never returned via the API.

## Executor Types

Both Python and Go workers support the following executor types:

| Type | Description | Notes |
|---|---|---|
| `shell` | Run a shell script (bash/sh) | Default executor |
| `external` | Run an external binary | Direct command execution |
| `python` | Run inline Python code | Python worker has venv/uv support |
| `powershell` | Run PowerShell scripts | Requires pwsh or powershell |
| `batch` | Run Windows batch scripts | Windows only |
| `sql` | Execute SQL queries | Supports postgres, mysql, mssql, oracle, mongodb; uses credential_ref for secrets |
| `http` | Make HTTP requests | REST triggers, webhooks, health checks; supports credential_ref for auth |
| `sensor` | Poll until a condition is met | HTTP or SQL sensor; runs on worker, not scheduler |

### Sensor Executor

Sensor jobs (`executor.type == "sensor"`) are dispatched and executed entirely on workers — the scheduler does **not** perform any external polling. This preserves the architectural boundary that the scheduler orchestrates and persists while workers execute.

A sensor worker thread polls a target at `poll_interval_seconds` intervals until either:
- The condition is met (HTTP: expected status received; SQL: query returns ≥1 row) → `run_end` status `success`
- `timeout_seconds` elapses → `run_end` status `failed`

Credentials (`credential_ref`) for sensor jobs are resolved by the scheduler at dispatch time and injected into the job envelope, exactly as for other executor types. Workers have no MongoDB access.

### Worker Capability Detection

Workers advertise only executor types that pass a concrete preflight check at startup:

| Capability | Preflight check |
|---|---|
| `shell` / `external` | At least one shell binary executes `exit 0` successfully |
| `python` | `HYDRA_PYTHON_PATH` or `python3`/`python` found and executable |
| `powershell` | `pwsh` or `powershell` executes `exit 0` successfully |
| `batch` | Windows OS detected |
| `sql` | Python present **and** `sqlalchemy` or `pymongo` importable |
| `http` | Always available (stdlib `urllib`) |
| `sensor` | Always available (HTTP sensor uses stdlib; SQL sensor requires same as `sql`) |

This fail-closed approach prevents dispatch of jobs to workers that lack the necessary runtime, rather than discovering the gap at execution time.

### Cross-Platform User Control

- **Impersonation**: Jobs can specify `executor.impersonate_user` to run commands as a different user via `sudo -n -u <user>` (Linux/macOS). The scheduler enforces OS affinity — impersonation jobs only dispatch to Linux/macOS workers.
- **Kerberos**: Jobs can specify `executor.kerberos` with `principal`, `keytab`, and optional `ccache` for Kerberos authentication bootstrap before execution.
- **Windows**: Use the service account model — run workers as the target user and use `allowed_users` affinity for routing.

### Workspace Caching

Workers maintain a persistent cache directory for source workspaces. Cache entries are keyed by `(url, ref, path, protocol)` hash and support:
- **LRU eviction** with configurable max size (`WORKER_WORKSPACE_CACHE_MAX_MB`)
- **Configurable TTL metadata** (`WORKER_WORKSPACE_CACHE_TTL`) based on the last recorded cache-use timestamp
- **Git fast-update** (fetch + checkout instead of full clone on cache hit)
- **Cache modes** per job: `auto` (default), `always`, `never`

## Run Lifecycle

### States

| State | Meaning |
|---|---|
| `pending` | Job has been enqueued in `job_queue:<domain>:pending` but not yet dispatched to a worker. |
| `dispatched` | Scheduler has pushed the job envelope to `job_queue:<domain>:<worker_id>`; the worker has not yet acknowledged execution start. |
| `running` | Worker emitted `run_start`; execution is in progress. |
| `success` | Worker emitted `run_end` with `status: success`. **Terminal.** |
| `failed` | Worker emitted `run_end` with `status: failed`, or the failover/timeout loop marked the run as failed. **Terminal.** |
| `timed_out` | Run exceeded its configured `timeout_seconds`; treated equivalently to failed for post-run actions. **Terminal.** |

`success`, `failed`, and `timed_out` are **terminal states**: a run document must not transition out of a terminal state. Post-run actions (scheduler-level retries, on-failure webhooks, e-mail alerts, and dependent-job triggers) fire exactly once when a run first enters a terminal state.

### State Transitions

```
pending → dispatched → running → success
                               → failed
                               → timed_out

failed / timed_out → (re-enqueued as a new run with a fresh run_id)
```

Retries and failover always create a **new** run document with a new `run_id`.  The original run document is preserved in its terminal state so the full history of attempts is available in MongoDB.

### Event Ingestion Semantics

Run lifecycle events are emitted by workers to `run_events:<domain>` in Redis and consumed by the **Run Event Loop** in the scheduler, which persists them to `job_runs` in MongoDB.

#### Idempotency guarantees

- **`run_start`**: Uses MongoDB `$setOnInsert`, which is a no-op if the document already exists.  Duplicate or replayed `run_start` events are dropped without updating the document.  A `run_start` that arrives after `run_end` has already marked the run terminal is also silently ignored.
- **`run_end`**: Guards against updating a document that is already in a terminal state.  Duplicate `run_end` events (including replays after scheduler restart) are detected and dropped before post-run actions can fire.

#### Anomalous sequence handling

| Scenario | Behaviour |
|---|---|
| Duplicate `run_start` | Logged at `WARNING`; no-op update (document unchanged, `append_worker_op` skipped). |
| `run_start` after terminal `run_end` | Logged at `WARNING`; ignored — terminal state is preserved. |
| Duplicate `run_end` (terminal state) | Logged at `WARNING`; entire `_handle_run_end` body skipped — post-run actions do not re-fire. |
| `run_end` before `run_start` | Logged at `WARNING`; a minimal fallback run document is created so the run is visible in history. Post-run actions fire once for this fallback document. |
| Concurrent insert on fallback | Handled via `DuplicateKeyError` catch; post-run actions are skipped if a concurrent `run_start` already committed the document in a terminal state. |

#### Crash-safety (staging queue)

The Run Event Loop uses Redis `RPOPLPUSH` to atomically move each event from `run_events:<domain>` to a per-domain staging queue `run_events:<domain>:processing` **before** processing it.  After successful (or unrecoverable) processing the event is removed from the staging queue with `LREM`.

On scheduler startup, `_recover_staging_events()` scans all `run_events:*:processing` keys and moves any leftover events back to their source queues, ensuring events that were in-flight during a crash are re-delivered.  Because event handlers are idempotent, re-delivery is safe.



Hydra instruments key stages of job execution so operators can observe where time is spent. The following timing fields are included in `run_end` events (and therefore persisted to MongoDB `job_runs`):

| Field | Description |
|---|---|
| `queue_latency_ms` | Time from job enqueue to worker thread start (dispatch latency) |
| `total_run_ms` | Wall-clock time from `run_start` to `run_end` |
| `source_fetch_ms` | Time spent fetching/updating the workspace (git clone, copy, rsync). `null` if no source is configured. |
| `env_prep_ms` | Time to prepare the Python execution environment (venv create, uv install). `null` for non-Python executors. |

Additionally, each worker records `startup_duration_ms` in its registration metadata (`workers:<domain>:<worker_id>`) and in the `start`/`restart` worker operation event. This measures the time from process start to first successful registration, capturing the cost of capability detection, dependency checks, and Redis connection setup.

### Querying timing data

Timing fields are available on `GET /history/` run records. To identify cold-start bottlenecks:

```bash
# Summarise source_fetch_ms for a specific job (using mongosh or any MongoDB client)
db.job_runs.aggregate([
  { $match: { job_id: "my-job-id" } },
  { $group: { _id: null, avg_fetch: { $avg: "$source_fetch_ms" }, p95_total: { $percentile: { input: "$total_run_ms", p: [0.95], method: "approximate" } } } }
])
```
