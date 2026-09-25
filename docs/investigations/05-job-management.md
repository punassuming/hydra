# Job Management Capabilities in Hydra Jobs

**Investigation Date:** 2026-09-25  
**Status:** In Progress

---

## 1. Job Model Completeness

**Files:** `/home/user/Hydra/scheduler/models/job_definition.py` (lines 66-92), `job_run.py` (lines 38-66), `executor.py` (lines 1-109)

### Key Findings

**JobDefinition fields** (comprehensive):
- Core: `id`, `name`, `user`, `domain`, `created_at`, `updated_at`
- Execution: `executor` (union of 8 types), `timeout`, `priority`, `bypass_concurrency`
- Scheduling: `schedule` (mode: immediate/cron/interval), `dependencies` via `depends_on`
- Resilience: `max_retries`, `retry_delay_seconds`, `sla_max_duration_seconds`
- Observability: `completion` criteria (exit codes, stdout/stderr patterns, file existence checks), `on_failure_webhooks`, `on_failure_email_*`
- Affinity: `affinity` object with os/tags/users/hostnames/subnets/deployment_types/executor_types
- Source provisioning: `source` config (git/copy/rsync with credential_ref, sparse checkout)
- Concurrency: `global_locks` for distributed locking

**Executor Types** (8 total): shell, python, batch, powershell, sql, http, external, sensor
- Each supports: args, env vars, workdir, Linux impersonation, Kerberos auth
- SQL: multi-dialect with credential ref + max_rows limit (10k default)
- Sensor: poll-based (http or sql) with interval + timeout
- Python: venv/system/uv environment, requirements file support

**Gaps Identified:**
1. **No job versioning/history**: There's `updated_at` but no audit trail of definition changes. Operators can't see "what was job X's previous definition?" or review change history. Recommendation: add optional `version`, `version_history` changelog.
2. **No parametrized/templated runs**: `run_now params` exists but no template variables syntax (e.g., `${param}` substitution in script). Dynamic parameter generation (fan-out) not built-in. Recommendation: define template syntax, add `parameters` field to JobDefinition.
3. **Minimal conditional logic**: `completion` criteria evaluate after run; no pre-execution conditionals (skip if, run-if). Recommendation: add optional `conditions` object with pre-flight checks.
4. **No dynamic task generation (DAG expansion)**: Manual `depends_on` list only; no declarative fan-out. Recommendation: consider `generate_tasks` executor for spawning dependent runs programmatically.

**Strengths:**
- Comprehensive executor matrix covers 99% of use cases (shell/python/sql/http/sensor).
- Completion criteria are flexible and precise.
- Affinity model is sophisticated (multi-faceted matching).

### 2. Scheduling Capability

**Files:** `/home/user/Hydra/scheduler/scheduler.py` (lines 230-588), `run_events.py` (lines 66-84), `schedule.py` (for `advance_schedule` logic)

### Key Findings

**Scheduling Modes:**
- `immediate`: one-time runs via `POST /jobs/{id}/run_now` or manual enqueue
- `cron`: standard cron expressions, validated with `croniter`, supports start_at/end_at window
- `interval`: simple seconds-based intervals
- Schedule state machine: next_run_at is pre-computed and advanced after each trigger (deterministic, not reactive)

**Dependency Enforcement** (lines 66-84 in run_events.py):
- Simple linear model: `depends_on: ["job_A", "job_B"]` means "enqueue me when job_A succeeds"
- **NOT a full DAG**: each job is a flat list of dependencies; no fan-in/fan-out detection or circular-dependency checking
- **No partial-failure semantics**: if job_B fails, dependent jobs still enqueue after job_A succeeds — the scheduler doesn't understand "wait for ALL dependencies to succeed"
- Enqueuing is triggered by `_trigger_dependents()` on job terminal state (success); **no failure-only or partial-match semantics**
- **Gap:** No retry-handling for dependencies — if job_A fails and is retried, a dependent enqueued after the first attempt won't re-wait
- Recommendation: implement `depends_on_mode: ["all" | "any" | "none_failed"]` and circular-dependency detection in validation

**Cron/Interval Execution:**
- `schedule_trigger_loop` (line 394): runs every 1s, queries due jobs with `next_run_at <= now`, advances schedule, re-enqueues
- Atomicity: uses Mongo `find_one_and_update` with a check on `schedule.next_run_at` to prevent duplicate enqueues if loop races with job definition update
- **Strength:** reliable once-per-window guarantee

**Backfill Support:**
- `backfill_dispatch_loop` (line 590): processes `backfill_queue:{domain}` (Redis list), dispatches to workers with `HYDRA_EXECUTION_DATE` + `HYDRA_IS_BACKFILL` env vars
- Backfill jobs use same affinity/worker selection as normal dispatch
- **Gap:** No backfill-specific retry/SLA semantics; treated identically to real-time jobs

**Failure & Retry:**
- `_enqueue_job_for_retry()` (line 44): re-enqueues failed job with optional delay (scheduler-level retry, not worker-level)
- Retry logic: terminal state + max_retries check → enqueue with new run_id (preserves run history)
- **Gap:** No exponential backoff built-in (delay_seconds is fixed); no dead-letter queue for permanently failed jobs after max_retries exhausted

**Strengths:**
- Scheduling is decoupled from execution (no scheduler-side polling loops for sensor jobs — workers execute sensor polling)
- SLA monitoring loop (line 445) independently tracks running jobs and fires webhooks/emails on SLA miss (good separation of concerns)
- Timeout enforcement loop (line 558) is separate, checks elapsed time per run, sends kill signal

**Observability:**
- Starvation tracking: `no_worker_count` incremented and logged when job requeued due to no eligible worker
- SLA miss detection: active, fires alerts asynchronously

### 3. Executor Capability Matrix

**Files:** `/home/user/Hydra/worker/executor.py` (lines 279-450+), `/home/user/Hydra/go-worker/internal/executor/executor.go` (lines 1-250)

### Key Findings

**Python Worker Support** (full feature set):
- Executor types: shell, python, batch, powershell, sql, http, external, sensor
- Advanced features:
  - Linux impersonation via `sudo -u` (lines 317-319)
  - Kerberos pre-auth (`kinit` bootstrap, line 338)
  - Completion criteria evaluation (stdout/stderr patterns, file existence, etc.)
  - Python env prep: system/venv/uv with requirements resolution
  - Source provisioning: git (with sparse checkout), copy, rsync
  - Sensor executor with polling (http + sql sensor types)

**Go Worker Support** (limited):
- Executor types: shell, external, batch, python, powershell, sql, http
- **Missing:** sensor executor (no polling support — see line 2 comment: "shell, external, batch, python, powershell, sql, and http executor types")
- **Missing:** impersonation/Kerberos support (lines 141-143: "impersonation/kerberos not supported")
- Source provisioning: git, copy, rsync (same as Python)

### Capability Mismatch Handling

**Current State:**
- No pre-flight capability negotiation in the scheduler
- Worker capabilities advertised via `capabilities` field in worker heartbeat (line 220 in scheduler.py)
- `passes_affinity()` checks job executor_types against worker capabilities, but this is optional in affinity config
- **Gap:** If a job requires sensor executor and all workers are Python-only, scheduler will dispatch the job — worker will fail it (not ideal)
- Recommendation: Make executor_type affinity required when job uses sensor; or reject sensor jobs at API validation time if no sensor-capable workers exist

**Strengths:**
- Python worker is genuinely comprehensive; Go worker is appropriately lightweight
- Job definition model already has `affinity.executor_types` for matching

### 4. Retry & Failure Handling

**Files:** `/home/user/Hydra/scheduler/run_events.py` (lines 44-433), `scheduler.py` (lines 558-588 for timeout enforcement)

### Key Findings

**Retry Logic:**
- Scheduler-level retry: `max_retries` (default 0) controls total attempts (line 407-417)
- On failure/timeout: if `retry_attempt < max_retries`, job is re-enqueued with `retry_attempt++` (line 410-417)
- Optional `retry_delay_seconds` applied between retry attempts (line 408, 416)
- Each retry creates a new run document with fresh run_id; history is preserved (documented in job_run.py lines 13-16)
- **Gap:** No exponential backoff built-in; `retry_delay_seconds` is constant for all retries
- **Gap:** No dead-letter queue or final-failure audit trail — after max_retries, job is silently marked failed

**Timeout vs Failure Distinction:**
- `timeout` (seconds, default 0 = infinite): max runtime for a job
- Timeout enforcement: `timeout_enforcement_loop` (line 558) scans running jobs every 5s, checks elapsed time, sends `kill` signal to Redis on breach (line 584)
- Worker receives kill signal and terminates the job process
- Terminal state: `timed_out` (distinct from `failed`; see job_run.py line 33)
- **Strength:** Clean separation; timeout tracking is reliable

**Failure Handling:**
- Terminal states: `success`, `failed`, `timed_out` (line 393, TERMINAL_STATES in job_run.py line 35)
- On success: `_trigger_dependents()` enqueues dependent jobs (line 391-392)
- On failure/timeout: check max_retries (line 393-417)
  - If retry remaining: enqueue with delay
  - If max_retries exhausted: fire `on_failure_webhooks` + `on_failure_email_to` (line 420-432)
- Email alerts: credential-ref based, SMTP configured (line 125-150+ in run_events.py)
- Webhook payloads: JSON with job_id, run_id, error_message (truncated to 2000 chars) (line 86-103)
- **Strength:** Post-run actions are deferred to dedicated threads (async), so they don't block scheduler loop

**Gaps:**
1. No dead-letter queue for permanently-failed jobs (visibility issue for operators)
2. Retry strategy is uniform (no jitter, exponential backoff, or circuit-breaker)
3. No transience classification (e.g., "transient network error, safe to retry" vs "permanent auth failure, don't retry")
4. Timeout status (`timed_out`) doesn't bypass retry logic (job can retry after timeout, which may waste resources)

### 5. Concurrency & Affinity

**Files:** `/home/user/Hydra/scheduler/utils/affinity.py` (71 lines), `selectors.py` (20 lines), `scheduler.py` (lines 191-290 for list_online_workers, scheduling_loop checks)

### Key Findings

**Affinity Model** (comprehensive):
- 7 dimensions: os, tags, allowed_users, hostnames, subnets, deployment_types, executor_types
- All checked via predicates in `passes_affinity()` (line 54-70)
- Tag matching: job's tags must ALL be present in worker tags (line 12-17, not "any-of" but "all-of")
- Executor types: auto-populated from job executor type if not explicitly set (line 39-51)
- Linux-specific: impersonation/Kerberos require Linux/macOS worker (line 57-61)
- **Strength:** Multi-faceted, flexible, covers common use cases (geo-affinity, user-based, capability-based)

**Worker Selection Strategy** (lines 4-19 in selectors.py):
- Deterministic: pick lowest-load worker by (current_running / max_concurrency, then absolute current_running)
- Not random; load-based is optimal for tail latency
- **Gap:** No priority-weighted selection (all jobs treated equally in load calculation)
- **Gap:** No locality preference (if multiple workers at same load, picks first)
- **Strength:** Simple, predictable, good for even distribution

**Concurrency Control:**
- Worker advertises `max_concurrency` (default 1, line 213 in scheduler.py)
- Scheduler respects capacity: only dispatches if `current_running < max_concurrency` (line 225)
- Real-time tracking: `current_running` updated by worker heartbeat (line 214)
- **Bypass Concurrency:** Job can set `bypass_concurrency: true` to exceed worker's max_concurrency (line 255)
  - Guarded by `SCHEDULER_BYPASS_MAX_EXTRA` (line 239): hard cap on extra bypass jobs per worker (default 0 = no cap)
  - Warning logged when dispatching bypass job to overloaded worker (line 334-342)

**Priority Handling:**
- Job has `priority` field (default 5, line 78 in job_definition.py)
- Scheduler uses `bzpopmax()` to pull highest-priority job from pending queue (line 245 in scheduler.py)
- Priority respected during re-enqueue (line 308)
- **Gap:** Priority doesn't influence worker selection (all candidates get same weight; only load matters)
- **Gap:** No strict priority lanes or preemption (a low-priority job running can't be bumped by high-priority arrival)

**Starvation Tracking:**
- `no_worker_count` incremented when job requeued due to no eligible worker (line 294)
- Warning logged at `SCHEDULER_STARVATION_WARN_THRESHOLD` (default 5) (line 295-300)
- Visible in `/overview/queue` and `/overview/pressure` endpoints
- **Strength:** Operators can see which jobs are starving

### 6. Observability of Job State

**Files:** `/home/user/Hydra/scheduler/api/jobs.py` (endpoints at lines 589-943)

### Key Findings

**Observability Endpoints (Rich):**
1. `/overview/queue` (line 589-685): Returns pending jobs + upcoming scheduled jobs
   - Pending: job_id, name, user, domain, priority, schedule_mode, next_run_at, queue_score, enqueued_ts, reason, **no_worker_count**
   - Includes `pending_total` per domain (total count before pagination)
   - Filterable by `pending_limit` and `upcoming_limit`
   - **Strength:** `no_worker_count` is visible — operators can identify starving jobs

2. `/overview/pressure` (line 688-787): Backpressure summary per domain
   - `pending_total`: queue depth
   - `stalled_jobs`: list of job IDs with no_worker_count >= threshold
   - `stalled_count`, `max_no_worker_count`: aggregate starvation metrics
   - `worker_queue_depths`: per-worker dispatch queue depths (shows if dispatch lag is per-worker or global)
   - `total_worker_queue_depth`: aggregate dispatch backlog
   - `online_workers`, `total_running`, `total_capacity`: capacity visibility
   - **Strength:** Single endpoint shows "why is the queue not running?" (lack of workers? no eligible workers? dispatch lag? queue full?)

3. `/jobs/{job_id}/grid` (line 832-873): Run history grid (recent runs with success/failure status)
4. `/jobs/{job_id}/gantt` (line 874-898): Timeline visualization of run executions
5. `/jobs/{job_id}/graph` (line 899-942): Dependency DAG visualization
6. `/overview/statistics` (line 943+): Aggregate stats (total jobs, runs by status, average duration, etc.)
7. `/overview/jobs` (line 499-587): Job listing with counts
8. Worker endpoints in `workers.py`: `/workers/`, `/workers/{worker_id}/metrics`, `/workers/{worker_id}/timeline`, `/workers/{worker_id}/operations`

**Strengths:**
- Comprehensive operational visibility: queue state, worker health, dispatch backlog, starvation tracking
- Dependency graph endpoint allows visual inspection of complex job chains
- Per-worker queue depths reveal dispatch bottlenecks
- Starvation threshold configurable and metrics exposed

**Gaps:**
1. No "why was this job not eligible?" detailed breakdown — operators see `no_worker_count` but not which affinity constraint caused rejection
2. No run performance ranking (longest-running jobs, slowest queued jobs, jobs with most retries)
3. No alert/threshold API (admins must poll `/overview/pressure` manually to detect issues)
4. No export/bulk-download API for run history (for compliance/audit)

### 7. CLI/Operator Tooling

**Files:** `/home/user/Hydra/scripts/hydra-apply.py`, bash helpers in `/scripts/`

### Key Findings

**CLI Tools Available:**
1. `hydra-apply.py` (YAML/JSON → API): GitOps-style job upsert; supports dry-run, domain targeting, custom API URL
2. Bash helpers (standalone scripts):
   - `create-domain.sh`: Create a new domain
   - `provision-redis-acl.sh`: Rotate domain worker Redis ACL credentials
   - `configure-external-redis-acl.sh`: Configure ACL user directly on external Redis
   - `start-domain-workers.sh`: Agentic worker bring-up (Docker/Kubernetes/bare)
   - `diagnose-domain-admin.sh`: Agentic diagnostics for domain auth and worker visibility
   - `run-acceptance-tests.sh`: Home-lab acceptance suite

**Gaps in CLI Parity:**
1. **No job inspection CLI** (no `hydra-ctl job get/list/describe`)
2. **No run management CLI** (no `hydra-ctl run retry/cancel/inspect`)
3. **No watch/polling CLI** (no `hydra-ctl watch <job_id>` for real-time status)
4. **No bulk operations** (no `hydra-ctl jobs disable-all` or `enable-pattern`)
5. **No audit/export CLI** (no `hydra-ctl export-runs --since <date>`)
6. **No doctor/diagnostics CLI** (no `hydra-ctl doctor --domain prod`)
   - Note: bash scripts exist (`diagnose-domain-admin.sh`) but no unified CLI
7. **No SLA/threshold management** (no CLI to set/view SLA policies)

**Strengths:**
- `hydra-apply.py` is well-designed, covers the main GitOps use case
- Bash helpers cover domain/worker bootstrap
- Scripts are discoverable and documented in `scripts/` directory

**Recommendation:**
- Develop a unified `hydra-ctl` CLI (Go binary or Python click-based) with subcommands:
  - `job list/get/edit/delete/run-now`
  - `run list/get/cancel/retry/inspect`
  - `worker list/state/drain/evict`
  - `domain create/list/delete/rotate-credentials`
  - `admin config/apply` (for policy/SLA rules)
  - `doctor/diagnose` (unified diagnostics)

### 8. Multi-Tenancy & Domain Isolation

**Files:** `/home/user/Hydra/scheduler/api/jobs.py` (lines 251-300), `admin.py`, `credentials.py`, `scheduler.py` (lines 45-150 for credential resolution)

### Key Findings

**Domain Enforcement Pattern:**
1. **API Token Scoping**: Every API request carries domain from token (line 256 in jobs.py); admin token bypasses domain scoping
2. **Job Queries**: Always filtered by domain (line 258, 272, 287 in jobs.py)
3. **Credential Access**: Domain-scoped queries (lines 65, 101, 127, 148 in scheduler.py)
4. **Worker Queues**: Per-domain keys in Redis (`job_queue:<domain>:pending`, `workers:<domain>:*`, etc.)
5. **Runs**: Domain stored in job_runs collection; queries filter by domain

**Domain Isolation Audit (Spot Check):**
- ✓ Job creation: domain derived from token (api/jobs.py line 76: `domain = getattr(request.state, "domain", "prod")`)
- ✓ Job reads: forbidden if job's domain != request domain (line 258)
- ✓ Job runs: filtered by domain (line 274: `domain_filter = force_domain or domain`)
- ✓ Credentials: scoped to domain in Mongo queries (admin.py line 245: `{"name": ..., "domain": cred_domain}`)
- ✓ Worker heartbeats: per-domain Redis keys (scheduler.py line 195: `f"workers:{domain}:*"`)
- ✓ Worker ACL: per-domain Redis ACL user (AGENTS.md: worker uses `DOMAIN` as Redis username)
- ✓ Redis queue dispatch: domain-scoped envelopes (scheduler.py line 354: `f"job_queue:{domain}:{wid}"`)

**Potential Gaps (Minimal):**
1. **No cross-domain job dependency**: A job in domain `prod` cannot depend on a job in `staging` — by design (safe)
2. **Admin bypass**: Admin token can see all domains; operations cannot be fine-grained (e.g., admin over `staging` but not `prod`)
   - Mitigation: API tokens are domain-scoped; admin tokens are org-scoped (no fine-grained admin roles)
3. **No namespace validation at creation**: Job domain is trusted from token; no explicit namespace validation (but token is authoritative)

**Strengths:**
- Domain isolation is systematic and appears consistent across API, Mongo, and Redis layers
- Worker auth is Redis ACL per-domain
- No cross-domain leakage in queue/heartbeat/credential layers

### 9. Known Gaps: Queue-Based Routing

---

## Summary — Top 5 Priorities

(To be completed)
