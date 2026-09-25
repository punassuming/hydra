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

### 6. Observability of Job State

### 7. CLI/Operator Tooling

### 8. Multi-Tenancy & Domain Isolation

### 9. Known Gaps: Queue-Based Routing

---

## Summary — Top 5 Priorities

(To be completed)
