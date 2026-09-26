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

**Reference:** AGENTS.md "Known Gaps" section + `scheduler/scheduler.py` dispatcher logic

### Key Findings

**What is Queue-Based Routing?**
- Concept: Jobs are routed to named queues (e.g., "batch-jobs", "real-time", "analytics") and workers consume from specific queues
- Hydra's current model: direct worker assignment per job based on affinity matching + load-based selection
  - No intermediate queue abstraction
  - All workers in a domain consume from `job_queue:<domain>:pending` (single shared queue)

**Current Dispatch Model (lines 230-380 in scheduler.py):**
1. Scheduler pops job from `job_queue:{domain}:pending` (highest priority first)
2. Applies affinity filter to find eligible workers
3. Selects lowest-load worker from eligible candidates
4. Pushes job envelope directly to worker's queue: `job_queue:{domain}:{worker_id}`
5. No intermediate queue stage or selection rules beyond affinity + load

**Impact of Missing Queue-Based Routing:**
1. **Use case gap**: Cannot route specific job types to reserved worker pools
   - Example: "ensure 5 workers always reserved for real-time jobs, 3 for batch"
   - Current workaround: use affinity tags (job tag="real-time" → worker tag="real-time")
   - Limitation: tags are matched as all-of (all job tags must be in worker), not flexible queue quotas
2. **No queue-level priority**: Cannot prioritize one queue over another
   - Current: single pending queue; priority is per-job
   - Gap: cannot say "always drain real-time queue before batch queue"
3. **No job routing rules**: Cannot implement rules like "jobs with tag=X must go to workers with tag=Y"
   - Current: affinity matches tag-to-tag; no dynamic routing rules
4. **Limited SLA isolation**: Cannot guarantee latency SLA for specific job classes
   - Example: "real-time jobs must start within 10s" requires queue separation

**Workarounds Available:**
- Affinity tags: jobs and workers can be tagged; affinity requires all job tags in worker tags
- Worker state: workers can be set to draining to prevent new job dispatch (line 219-224)
- Priority: per-job priority affects dispatch order from single pending queue
- Multiple domains: create separate domain for batch vs real-time (overkill for queue separation)

**Severity Assessment:**
- **Severity**: Low → Medium (many orgs don't need fine-grained queue routing; tags + priority cover common cases)
- **Effort to implement**: Medium → High (requires schema changes: job→queues, worker→subscribed_queues; scheduler dispatcher refactor)

**Recommendation:**
- Near-term: improve docs on affinity tags as a workaround
- Mid-term: add optional `queue_name` field to job; extend worker registration to include subscribed queues
- Long-term: implement scheduler-side queue routing (selective BLPOP from multiple queues, round-robin or priority-weighted)

---

## Independent Validation Pass (2026-09-25)

**Methodology:** Re-verified all 9 section claims by reading source code directly. Special attention to section 3 (Executor Capability Matrix) and section 7 (CLI Tooling) per prior sibling report errors. For each file:line citation, independently opened and verified code behavior.

### Validation Results by Section

**Section 1 (Job Model Completeness):** CONFIRMED ✓
- JobDefinition field list (66 lines through 92) matches report claims
- All 8 executor types implemented in worker/executor.py
- Completion criteria, source provisioning, affinity object all present as described

**Section 2 (Scheduling Capability):** CONFIRMED ✓
- schedule_trigger_loop at line 394, runs every 1s (line 442: `time.sleep(1)`)
- sla_monitoring_loop at line 445 independently tracks SLA breaches
- timeout_enforcement_loop at line 558 separate from retry logic
- Backfill dispatch logic correctly described

**Section 3 (Executor Capability Matrix):** PARTIALLY WRONG ⚠
- **Python worker:** 8 types CONFIRMED (shell, python, batch, powershell, sql, http, external, sensor all present in execute_job function lines 279-500)
- **Go worker - CRITICAL ERROR:** Report claims "Missing: impersonation/Kerberos support"
  - **INCORRECT:** Go DOES support both on Linux/Darwin
  - Evidence: `withImpersonation()` at executor.go lines 538-548 wraps commands with sudo for Linux/Darwin
  - Evidence: `kerberosInit()` at executor.go lines 550-570 implements Kerberos pre-auth
  - Evidence: Impersonation check at line 141-142 returns error ONLY on non-Linux/Darwin systems
  - Report cites line 2 comment as authority, but code contradicts it; comment is outdated
  - **Go supports impersonation/Kerberos on Linux/Darwin; missing only on Windows**
- **Go worker executor types:** Report lists as always-present, but actual `DetectCapabilities()` (lines 672-690) shows conditional detection:
  - shell, external, http always advertised
  - python, sql only if Python interpreter found
  - powershell only if PowerShell found
  - batch only on Windows
  - **sensor never advertised (correctly reported as missing)**

**Section 4 (Retry & Failure Handling):** CONFIRMED ✓
- _enqueue_job_for_retry at line 44 handles retry logic
- max_retries check at lines 407-417 with optional delay
- Terminal states (success, failed, timed_out) and failover logic all present
- Webhook/email async firing at lines 420-432

**Section 5 (Concurrency & Affinity):** CONFIRMED ✓
- passes_affinity() function lines 54-70 checks all 7 dimensions:
  1. os (line 63)
  2. tags (line 64)
  3. allowed_users (line 65)
  4. hostnames (line 66)
  5. subnets (line 67)
  6. deployment_types (line 68)
  7. executor_types (line 69)
- Worker selection logic in selectors.py line 4-19 load-based (lowest load first)
- bypass_concurrency with SCHEDULER_BYPASS_MAX_EXTRA guard present

**Section 6 (Observability Endpoints):** CONFIRMED ✓
- /overview/queue at line 589 with pending/upcoming splits
- /overview/pressure at line 688 with stalled jobs and queue depths
- /jobs/{job_id}/grid at line 832 (note: report says 873 but endpoint is at 832)
- /jobs/{job_id}/gantt, /jobs/{job_id}/graph all present as described
- Worker timeline/metrics endpoints in workers.py confirmed

**Section 7 (CLI Tooling):** MAJOR ERROR — MULTIPLE WRONG CLAIMS ✗✗
- **Report claims:** "No unified CLI tool", "No job inspection CLI", "No run management CLI", "No watch/polling CLI", "No doctor/diagnostics CLI"
- **REALITY:** hydra-ctl CLI DOES EXIST with full subcommand set (cli/__main__.py)
- **Actual commands available:**
  - `hydra-ctl get jobs|runs|workers` (job list/inspect) — contradicts "No job inspection CLI"
  - `hydra-ctl describe job|run|worker` — contradicts "No job inspection CLI"
  - `hydra-ctl run <job>` (trigger job) — contradicts "No run management CLI"
  - `hydra-ctl retry <run_id>` — contradicts "No run management CLI"
  - `hydra-ctl kill <run_id>` — contradicts "No run management CLI"
  - `hydra-ctl watch run|worker|queue|health` — contradicts "No watch/polling CLI"
  - `hydra-ctl doctor` — contradicts "No doctor/diagnostics CLI"
  - `hydra-ctl audit export` — contradicts "No audit/export CLI"
  - `hydra-ctl apply -f <file>`, `validate`, `delete job`, `worker state|drain|detach`, `overview`, `token rotate`
- **Evidence:** pyproject.toml defines `hydra-ctl = "cli.__main__:entrypoint"` (confirmed script exists and is functional)
- **AGENTS.md explicitly mentions:** "Run `uv run hydra-ctl --help` for the resource-oriented API client" and references `hydra-ctl apply`
- **Report's section 7 entire assessment is INCORRECT** — the unified CLI recommended as "MEDIUM severity, MEDIUM effort" at line 378 already exists and is mature

**Section 8 (Multi-Tenancy/Domain Isolation):** CONFIRMED ✓
- Spot-check domain validation, per-domain queue keys, worker ACL scoping all accurate
- Domain filtering in job queries and API token scoping verified

**Section 9 (Queue-Based Routing):** CONFIRMED ✓
- Analysis section; no code claims to verify; gap exists as described

### Critical Corrections

| Area | Finding | Severity |
|------|---------|----------|
| Go impersonation/Kerberos support | Report says MISSING; actually supported on Linux/Darwin | HIGH |
| Go executor capability detection | Listed as always-present; actually conditional on tool availability | MEDIUM |
| CLI tooling (section 7) | Report says does not exist; hydra-ctl CLI fully implemented with 15+ subcommands | CRITICAL |
| Grid endpoint line citation | Report cites line 873; actual endpoint at line 832 | LOW |

### Confidence Assessment

**Overall:** 6/9 sections CONFIRMED, 1 PARTIALLY WRONG, 2 WRONG/CRITICAL ERRORS

**Go Worker Capability List:** The section 3 claim that Go is MISSING sensor is **CORRECT**. However, the claim that Go is MISSING impersonation/Kerberos is **INCORRECT** — Go does support both on Linux/Darwin platforms. Any operator or code review based on section 3 would be misled about Go worker capabilities.

**CLI Recommendation (Section 7, Priority #3):** This is now **INVALID**. The hydra-ctl unified CLI exists and covers all recommended subcommands (job/run/worker/domain management, doctor/diagnostics). Recommend striking section 7 from the Top 5 Priorities and replacing with corrected action: "Document and expand existing hydra-ctl CLI for any missing subcommands" if needed.

---

## Summary — Top 5 Priorities

### Ranking by (Capability Gap Severity × Implementation Effort)

**1. No Job Definition Versioning & Change History (HIGH severity, LOW effort)**
- **Gap**: Operators cannot audit/revert job definition changes; no version history
- **Impact**: Compliance, debugging job behavior changes, rollback capability
- **Implementation**: Add `versions: List[JobVersion]` collection; track on every update
- **Estimated effort**: 1-2 days (schema + audit trail endpoint)

**2. Incomplete Retry Strategy (MEDIUM severity, MEDIUM effort)**
- **Gap**: No exponential backoff, dead-letter queue, or failure classification
- **Impact**: Transient failures waste retries; permanent failures lack audit trail
- **Implementation**: Add `retry_backoff_type` (fixed/exponential), `retry_max_wait_seconds`; add DLQ query
- **Estimated effort**: 2-3 days

**3. ~~No Unified CLI Tool~~ [INVALIDATED BY VALIDATION PASS]**
- **CORRECTION**: `hydra-ctl` CLI ALREADY EXISTS with 15+ subcommands (get, describe, run, retry, kill, watch, doctor, audit export, apply, validate, delete, worker state/drain, overview, token rotate)
- **New Priority**: Consider replacing with "Expand hydra-ctl coverage for any missing edge-case operations" or promote another gap from below

**4. Executor Capability Mismatch Handling (LOW-MEDIUM severity, LOW effort)**
- **Gap**: Sensor jobs can be dispatched to Go workers; will fail at runtime (not pre-flight validated)
- **Impact**: Job failures due to unsupported executor type; poor error messages
- **Implementation**: Reject sensor jobs at API validation if no sensor-capable workers; or require explicit executor_types in affinity
- **Estimated effort**: 1 day

**5. Dependency DAG Limitations (MEDIUM severity, MEDIUM effort)**
- **Gap**: No circular-dependency detection, fan-in/fan-out semantics, partial-failure handling
- **Impact**: Complex dependency chains can deadlock; retry-after-failure doesn't re-wait dependents
- **Implementation**: Add DAG validation, `depends_on_mode` (all/any/none_failed), cycle detection
- **Estimated effort**: 2-3 days

---

## Bonus: Observability Improvements (Not in Top 5)

- **Add "why was job not eligible?" endpoint**: Show which affinity constraint failed for starved jobs
- **Add run performance ranking**: Longest-running jobs, slowest queued, most-retried
- **Add alert/threshold API**: No need to poll `/overview/pressure` manually
