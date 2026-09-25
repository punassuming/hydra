# Hydra Jobs vs. Airflow, Dagster, Argo: Best Practices Comparison

**Date:** 2026-09-25  
**Status:** Live Investigation - In Progress  
**Researcher:** Claude Code Agent  

---

## 1. Job/DAG Definition Model

### What Others Do

**Airflow 3.0+ (April 2025)**
- **TaskFlow API**: Python decorator-based DAG definition (@dag, @task) with implicit task dependencies via function parameters
- **DAG Versioning (AIP-36)**: Each DAG code push creates a new version; UI shows changes over time; runs can specify which version to use
- **Task SDK**: Stable `airflow.sdk` namespace replaces internal imports; forward-compatible authoring interface
- **Multi-step DAGs**: All tasks/operators within one DAG definition; explicit task ordering via XCom passing and task dependencies

**Dagster (2025-2026)**
- **Software-Defined Assets (SDAs)**: Assets (not tasks) as first-class abstractions; each asset declares its upstream dependencies and materialization logic
- **Typed I/O**: Assets have typed inputs/outputs; partitioning is a first-class `PartitionsDefinition` object all downstream assets reason about
- **Asset Lineage**: Auto-generates from code; dbt integration auto-detects lineage from manifest without manual wiring
- **Multi-step workflows**: Implicit via asset dependencies; no separate "job" concept—asset graph IS the workflow

**Argo Workflows (v2.7+, 2025-2026)**
- **WorkflowTemplates**: Reusable, cluster-resident workflow definitions; supports parametrization
- **DAG + Steps templates**: Two ways to define execution order—DAG (task graph) or Steps (sequential)
- **Parametrized definitions**: Arguments passed from Workflow to templates; TemplateRef for cross-template composition
- **Multi-step workflows**: Each Workflow is a DAG or sequence; templates are reusable building blocks

### How Hydra Does It

In `scheduler/models/job_definition.py`:
- **Single-executor-per-job model**: Each `JobDefinition` has ONE `executor` (shell/python/sql/http/external/sensor)
- **Job dependencies via `depends_on`**: Simple list of job IDs; scheduler enqueues job after dependencies complete
- **No multi-step DAG within a job**: If you need 3 sequential steps, create 3 separate jobs + link them with `depends_on`
- **Schedule + completion criteria inline**: `ScheduleConfig`, `CompletionCriteria` are part of the job definition
- **No versioning**: Job updates replace the entire definition; no history of code/config versions

### Gap Assessment & Recommendations

**Key gaps:**
1. **No multi-step DAGs within a job** – Requires N jobs for N steps; causes job proliferation and hides workflow structure
2. **No job versioning** – Updates clobber prior versions; no audit trail or ability to re-run with old code
3. **No typed I/O** – Parameter passing between jobs is untyped and implicit
4. **No reusable templates** – Must create each job via UI/API; no job template library (like Argo WorkflowTemplate)

**Recommendations:**
1. **Add multi-step DAG support (HIGH)** → `scheduler/models/job_definition.py`: Add `steps: List[StepDefinition]` as alternative to single `executor`. Each step inherits source/affinity but can override. Scheduler chains step outputs to next step's input. Reduces job proliferation; aligns with Airflow/Dagster/Argo mental model.
2. **Introduce job versioning (MEDIUM-HIGH)** → `scheduler/models/job_definition.py`, `scheduler/api/jobs.py`: Add `job_version` (auto-incremented), store all versions in Mongo, expose `GET /jobs/{id}/versions`, `GET /jobs/{id}/versions/{version}`. Matches Airflow 3.0's DAG versioning; enables audit trail + re-runs with old code.
3. **Make parameters first-class (MEDIUM)** → `scheduler/models/job_definition.py`: Add `parameters: Dict[str, ParameterDefinition]` with type hints, defaults, descriptions. Support `${param.name}` references in executor config. Unblocks templating in future.
4. **Design job templates (FUTURE)** → New `scheduler/models/job_template.py`: Define `JobTemplate` as reusable parametrized definition. Expose `POST /job_templates/`, `GET /job_templates/{id}/instantiate`. Enables job library.

---

## 2. Job Creation UX/API

### What Others Do

**Airflow (3.0+, 2025)**
- **DAG-as-code in Git**: DAGs live as Python files in Git repositories; Airflow syncs from Git via DAG bundles or direct folder scanning
- **DAG Bundles**: Cluster can pull DAGs from private Git repos; versioning tied to Git commits
- **Code view in UI**: Quick view of DAG source code in browser, integrated with Git plugin for history navigation
- **Programmatic creation**: Primarily code-first; UI is read-only for DAG definition (dag editing not standard in OSS)
- **No UI drag-and-drop**: DAGs must be written in Python; no low-code/visual editor

**Dagster (2025-2026)**
- **Asset decorators in Python**: @asset decorators in code files; live in Dagster projects (git-backed)
- **Launchpad UI**: Click "Materialize" + "Open Launchpad" on an asset job to interactively supply run config (YAML editor, typeahead, validation, scaffold missing values)
- **Configuration-driven runs**: Run-time config passed via Launchpad, not job definition itself; fully typed schema
- **Dagster Cloud**: Cloud version supports team workspaces; deployment tied to Git branch
- **UI for viewing/configuring only**: Definition is code; UI is for launching/monitoring/inspecting

**Argo Workflows (v2.7+, 2025)**
- **YAML-first workflow definitions**: Workflows are Kubernetes CRDs; stored in Git, applied via kubectl or `argo submit`
- **`argo submit` CLI**: Primary submission method: `argo submit workflow.yaml [--watch, --wait]` with parameter override support
- **WorkflowTemplates in cluster**: Reusable templates reside as CRDs; referenced by concrete Workflows
- **Native Git sync**: Can use ArgoCD or git-sync sidecar to continuously reconcile workflows from Git
- **Kubernetes-native**: Full GitOps via kubectl + ArgoCD; parameters via arguments in YAML or CLI flags

### How Hydra Does It

In `scheduler/api/jobs.py`, `ui/src/components/`, and `scripts/hydra-apply.py`:
- **YAML/JSON file-based upsert via `hydra-apply.py`**: Reads `jobs.yaml`, applies via `POST /jobs/` (create) or `PUT /jobs/{id}` (update)
- **Idempotent**: Matches jobs by name within domain; re-applying file is safe (upsert semantics)
- **UI job creation**: React form in `ui/src/components/job-form/` with modal for executor type selection
- **AI job generation**: `POST /ai/generate_job` accepts natural language → JSON; integrated into UI New Job form
- **No native Git sync**: `hydra-apply.py` is manual CLI tool; no ArgoCD-style reconciliation loop
- **Parameter support**: Jobs accept `params` in API, but not first-class in job definition

### Gap Assessment & Recommendations

**Strengths:**
- ✅ GitOps story via `hydra-apply.py` is solid; idempotent upsert is better than many tools
- ✅ YAML/JSON format is simple and portable; easy to version in Git
- ✅ AI job generation (natural language → JSON) is a unique UX advantage over Airflow/Argo

**Gaps:**
1. **No native Git sync loop** – `hydra-apply.py` is manual; no ArgoCD-style continuous reconciliation
2. **No code-based job definition option** – Unlike Airflow (Python), Dagster (Python decorators), Argo (CRDs); Hydra is UI/API-only
3. **No first-class run configuration** – Unlike Dagster's Launchpad or Argo's parameter passing; Hydra conflates job config with run config
4. **No interactive run launcher** – No equivalent to Dagster's Launchpad (config editor, typeahead, validation)

**Recommendations:**
1. **Implement GitOps reconciliation loop (MEDIUM)** → New service module `scheduler/gitops_loop.py`: Watch Git repo for job definition changes, auto-apply via internal API (same idempotency as `hydra-apply.py`). Expose `HYDRA_GITOPS_REPO` + `HYDRA_GITOPS_BRANCH` env vars. Benefit: True GitOps; CI/CD integration; no manual CLI calls.
2. **Separate run-time config from job definition (MEDIUM-HIGH)** → `scheduler/models/job_definition.py`: Add `required_run_config: Dict[str, ParameterDefinition]` to job; `POST /jobs/{id}/run` accepts config payload separately. Implement Launchpad-style UI in `ui/src/components/RunLauncher.tsx` with schema validation. Benefit: Closer to Dagster/Argo model; clearer job intent vs run variation.
3. **Add optional Python/YAML code-based definition option (LOW-MEDIUM, future)** → Research language-agnostic DSL or support both `hydra-apply.py` + a `hydra define` Python API. Benefit: Appeals to engineers from Airflow/Dagster backgrounds.
4. **Enhance `hydra-apply.py` with --watch flag (LOW)** → Poll Git repo for changes; auto-apply periodically. Quick win toward GitOps story until full reconciliation loop is ready.

---

## 3. Monitoring & Observability Standardization

### What Others Do

**Airflow 3.x (2025-2026)**
- **Grid View**: Per-DAG-run task instance matrix (runs × tasks); each cell shows task status with mini-timeline duration; fast streaming aggregation
- **Gantt View**: Rebuilt calendar/Gantt charts with filtering; interactive timeline showing task parallelism and duration
- **Graph View**: DAG structure visualization; clickable nodes showing task details
- **Task Instance Timeline**: Mini Gantt-style visualization per task, showing queue→start→end duration
- **Multi-DAG monitoring**: Limited; focus is per-DAG views, not cross-DAG runs/lineage

**Dagster (2025-2026)**
- **Asset Catalog**: Central asset browser by compute-kind, asset-group, owner, tags; shows freshness/health
- **Materializations view**: Per-asset history with metadata per materialization (row count, schema, data preview)
- **Run Timeline**: Tracks which partitions succeeded/failed/missing; complete data coverage picture
- **Asset Lineage**: Auto-generated upstream/downstream; includes dbt models without manual wiring
- **Freshness/SLA tracking**: Asset-level freshness policy, visible in UI with alerts
- **Full-system observability**: Global asset lineage view (all assets, all dependencies)

**Argo Workflows (2025-2026)**
- **DAG Visualization**: Live node-level visualization; node color indicates state (pending→running→success/fail)
- **Workflow monitoring**: Per-workflow detail page with logs, events, node status
- **Cron Workflow UI**: Create/view scheduled workflows; event-driven triggers via Argo Events
- **Limited cross-workflow views**: No native "all workflows" timeline or cross-workflow dependency view
- **Embedded widgets**: Can embed workflow status/progress in external dashboards

### How Hydra Does It

In `scheduler/api/jobs.py` and `ui/src/components/`:
- **Grid View** (`GET /jobs/{id}/grid`): Per-job run matrix (runs × runs detail); shows run status, duration, logs
- **Gantt View** (`GET /jobs/{id}/gantt`): Timeline of job runs; shows queue latency, run duration, retries
- **Graph View** (`GET /jobs/{id}/graph`): DAG structure for job's `depends_on` dependencies; visual dependency tree
- **Worker Timeline** (`GET /workers/{id}/timeline`): Per-worker execution spans; shows concurrent jobs on a worker
- **Overview Pressure** (`GET /overview/pressure`): Per-domain backpressure summary; pending depth, stalled counts, worker capacity
- **Overview Queue** (`GET /overview/queue`): Pending job queue rows + upcoming scheduled jobs per domain
- **No asset/data lineage**: Monitoring is job/task-centric, not data/asset-centric like Dagster

### Gap Assessment & Recommendations

**Strengths:**
- ✅ Grid, Gantt, Graph views are present and well-structured
- ✅ Worker-level timeline + operations tracking is strong (better than Airflow's per-task focus)
- ✅ Pressure/queue overview is useful for capacity planning

**Gaps:**
1. **No cross-domain/global job timeline** – Unlike Airflow's overview, no "all jobs across all domains" Gantt
2. **No asset/data lineage visualization** – Only job dependency graph; no view of data/artifact flow like Dagster
3. **No job/run freshness tracking** – Unlike Dagster's asset freshness policy + UI alerts
4. **Limited multi-run correlation** – Hard to compare similar runs (e.g., "why did this run take 2x longer?")
5. **No materialization/output catalog** – Job outputs are implicit; no centralized "what data was produced" view

**Recommendations:**
1. **Add cross-domain/global run timeline (MEDIUM)** → `scheduler/api/history.py`: New endpoint `GET /overview/run_timeline?domains=prod,staging&time_range=24h` returning flattened runs from all domains, formatted for global Gantt rendering. Benefit: Spot bottlenecks across organization; see impact of one domain's slowness on others.
2. **Introduce job output/artifact tracking (MEDIUM-HIGH, future)** → New `scheduler/models/job_artifact.py`: Define artifact output schema (e.g., `type: "file" | "dataset" | "metric"`, uri, metadata). Store in `job_artifacts` Mongo collection; expose `GET /jobs/{id}/artifacts/{run_id}`. UI: Artifact catalog sidebar on run detail page. Benefit: Moves toward Dagster's asset-centric model; enables data lineage in future.
3. **Add "compare runs" view (MEDIUM)** → `ui/src/components/CompareRuns.tsx`: Select 2+ runs of same job; side-by-side logs, duration breakdown, executor config diff. Benefit: Helps debug performance regressions ("why did run X take 2x longer than Y?").
4. **Extend Graph View to show cross-job lineage (LOW-MEDIUM, future)** → Enhance `GET /jobs/{id}/graph` to include transitive dependencies (jobs that depend on this job's outputs). Build UI tree showing upstream+downstream jobs. Benefit: Full dependency graph visibility; prerequisite for artifact lineage.

---

## 4. Retry/Backfill/SLA Semantics

### What Others Do

**Airflow (3.x, 2025)**
- **Retry delay**: `retry_delay` (fixed) + `retry_exponential_backoff` (True/factor) for progressive backoff
- **SLA**: `sla` (timedelta); triggers `on_sla_miss_callback` when exceeded; visible in Grid View
- **Backfill**: `airflow backfill` CLI for historical data re-runs over explicit date range; scheduler-managed in 3.x
- **Callbacks**: `on_failure_callback`, `on_success_callback`, `on_retry_callback` for monitoring/alerting
- **Catchup**: Automatic re-run of missed DAG runs from start_date onward; separate from backfill

**Dagster (2025-2026)**
- **Retry policy**: Per-op/asset retry policy with configurable backoff strategy and max retries
- **Backfill policy**: Single-run (all partitions in one run) or multi-run (batched partitions); configurable max_partitions_per_run
- **Partition-aware**: BackfillPolicy respects asset partitioning; can backfill specific partition ranges
- **Sensor-driven backfills**: AutomationConditionSensorDefinitions auto-emit backfills when multiple partitions needed
- **No explicit SLA**: Freshness policy tracks asset staleness; freshnessChecks emit alerts

**Argo Workflows (2025)**
- **Retry strategy**: `retryStrategy` per task with `limit` (max attempts) and `maxDuration` (timeout)
- **Backoff**: Exponential backoff with `duration`, `factor`, `maxDuration` parameters
- **Workflow deadline**: `spec.activeDeadlineSeconds` sets wall-clock lifetime; retry/backoff consume this budget
- **Pod deadline**: `template.activeDeadlineSeconds` for individual pod-level timeouts
- **SLA**: No native SLA concept; must implement via deadline monitoring + external alerting

### How Hydra Does It

In `scheduler/models/job_definition.py` lines 76-91:
- **Retry**: `max_retries` (int, default 0) + `retry_delay_seconds` (int, default 0)
- **SLA**: `sla_max_duration_seconds` (optional int); scheduler logs warning if run exceeds
- **On failure**: `on_failure_webhooks` (list of URLs) + `on_failure_email_to` (email list) + credential ref
- **Backfill**: `POST /jobs/{id}/backfill` endpoint; takes `start_date`, `end_date`, interval; creates adhoc runs
- **No exponential backoff**: Fixed `retry_delay_seconds` only; no factor/multiplier option
- **Partition awareness**: Backfill is date-range agnostic; no partition concept in job model

### Gap Assessment & Recommendations

**Strengths:**
- ✅ Backfill endpoint exists; covers basic re-run needs
- ✅ SLA tracking + webhook/email notifications are present
- ✅ Retry delay is simple and explicit

**Gaps:**
1. **No exponential backoff** – Fixed delay only; Airflow/Argo support progressive backoff (better for transient failures)
2. **No partition-aware backfill** – Unlike Dagster's BackfillPolicy; Hydra backfill is date-agnostic, no batch-size control
3. **SLA callback inflexible** – Webhooks/email only; no on_sla_miss_callback like Airflow
4. **No freshness policy** – Unlike Dagster's asset freshness tracking; SLA is run-level only
5. **No backoff cap** – Unlike Argo's maxDuration; runaway retry loops could consume budget indefinitely

**Recommendations:**
1. **Add exponential backoff support (MEDIUM)** → `scheduler/models/job_definition.py`: Add `retry_backoff_factor: float = 1.0` (default 1.0 = no exponential backoff; 2.0 = double each retry). Cap with `retry_max_delay_seconds: int = 3600`. Scheduler applies: `delay = min(retry_delay_seconds * (factor ** attempt), retry_max_delay_seconds)`. Benefit: Better resilience for transient failures; matches Airflow/Argo.
2. **Extend backfill with partition/batch support (MEDIUM-HIGH, future)** → `scheduler/models/job_definition.py`: Add optional `partition_config: PartitionDefinition` to job (e.g., daily, hourly, by-field). Backfill honors partitions: `POST /jobs/{id}/backfill` with `max_partitions_per_run=10` batches partitions into runs. Store partition state in `job_partition_state` Mongo collection. Benefit: Aligns with Dagster's approach; enables efficient large-scale backfills.
3. **Add freshness policy (LOW-MEDIUM, future)** → New `scheduler/models/freshness_policy.py`: Define asset freshness expectation (e.g., "materialized within 4 hours"). Job tracks last successful run; scheduler checks staleness; UI shows freshness health. Benefit: Longer-term alignment with Dagster's observability model.
4. **Enhance SLA with custom callback hooks (MEDIUM)** → `scheduler/api/jobs.py`: Support `on_sla_miss_callback` (function call) in addition to webhooks/email. Benefit: Allows custom remediation (e.g., auto-retry, notify PagerDuty).

---

## 5. Sensors & Event-Driven Triggering

### What Others Do

**Airflow (3.x, 2025)**
- **Deferrable operators/sensors**: Async, non-blocking; task defers with a Trigger; frees worker slot while waiting
- **Triggerer process**: Separate daemon manages many async triggers; fires events when conditions met
- **Event-driven architecture**: Core design shift in Airflow 3; moves away from synchronous polling
- **Sensor modes**: `poke` (synchronous, full worker slot) vs `deferrable` (async, efficient)
- **Callback-based triggering**: Task resumes from deferred state when trigger fires
- **Config**: `operators.default_deferrable = True` enables async by default

**Dagster (2025-2026)**
- **Sensors**: Poll an external resource at intervals; materialize assets when condition met
- **Schedules**: Time-based automation; construct from partitioned jobs
- **Dynamic partitions**: Sensors can detect new partitions (e.g., files in S3) and materialize dynamically
- **Asset sensors**: Trigger downstream assets when upstream assets materialize
- **Declarative automation**: Multi-asset automation rules (partitions, sensor fusion, backfills)
- **No deferral concept**: Sensors are worker-backed polls, not event-driven Triggers

**Argo Events (2025-2026)**
- **Event sources**: 20+ integrations (S3, Kafka, webhooks, cron, GCP PubSub, SQS, etc.)
- **Sensors**: Detect events from sources; emit events when condition met
- **Triggers**: 10+ actions (create K8s object, invoke workflow, webhook, messaging)
- **Argo Workflow trigger**: Can trigger Argo Workflows directly from Argo Events sensors
- **Fully event-driven**: No polling loop; events flow through event broker
- **Integration**: Native K8s events + custom event sources

### How Hydra Does It

In `scheduler/models/executor.py` lines 80-96 and `worker/executor.py`:
- **Sensor executor type**: `executor.type == "sensor"` with `sensor_type: "http" | "sql"`
- **Worker-side polling**: Worker polls HTTP endpoint or SQL query at `poll_interval_seconds` intervals
- **Blocking poll pattern**: Worker blocks on sensor job; holds concurrency slot while waiting
- **Target monitoring**: Sensor checks `target` (URL or SQL query) for success/failure
- **No event broker**: No external event system; sensor job *is* the polling loop
- **Scheduler disptches like any job**: Sensor jobs are treated as normal jobs; no special orchestration
- **Parameters**: `timeout_seconds` caps polling duration

### Gap Assessment & Recommendations

**Strengths:**
- ✅ Sensor executor exists; covers basic HTTP/SQL polling use cases
- ✅ Flexible target (URL or query); covers many scenarios

**Gaps:**
1. **Worker slot exhaustion** – Sensor job blocks a worker concurrency slot during entire poll window; scales poorly
2. **No event broker** – Unlike Argo Events or Airflow Triggers; Hydra has no async event system
3. **Limited event sources** – Only HTTP/SQL; no S3, Kafka, webhooks, cron, etc.
4. **No deferral model** – Unlike Airflow 3.x's async Triggers; no way to free worker slot while waiting
5. **Implicit polling** – No visibility into how often sensor checks; no backpressure/throttling

**Recommendations:**
1. **Document current polling cost & limitations (LOW)** → Add comment in `scheduler/models/executor.py` explaining that sensor jobs consume worker concurrency for full duration. Recommend alternative: external job triggers sensor job on-demand (e.g., via webhook/API).
2. **Add event-source diversity (MEDIUM, future)** → Consider pluggable event source backends (HTTP, SQL, S3, Kafka). Expose as new sensor types. Requires event broker integration (Redis pub/sub, external service).
3. **Explore deferral pattern (MEDIUM-HIGH, future)** → Research Airflow-style Triggerer pattern: sensor setup emits trigger condition, scheduler holds deferred task, event fires when condition met. Would require significant refactoring of worker/scheduler boundary.
4. **Implement sensor backpressure/throttling (LOW-MEDIUM, future)** → Add `max_concurrent_sensors` worker config to limit how many sensor jobs a single worker runs. Benefit: Prevent sensor job starvation of normal jobs.
5. **Add webhook-trigger as alternative (MEDIUM, future)** → Support external systems triggering Hydra jobs via `POST /webhooks/trigger?job_id=X&secret=Y`. Benefit: True event-driven without polling; matches Argo Events pattern.

---

## 6. Multi-Tenancy & RBAC Standardization

### What Others Do

**Airflow (3.x, 2025)**
- **RBAC model**: Roles (Admin, Viewer, User, custom) with fine-grained permissions (can_read, can_edit per DAG)
- **DAG-level access**: Each DAG is a View; assign permissions per-DAG or by tag
- **Multi-team support**: Experimental in 3.x; provides UI + API-level isolation between teams
- **Default roles**: Admin (all permissions), Viewer (read-only), User (DAG ownership + execution)
- **Tag-based grouping**: Scale permissions across hundreds/thousands of DAGs via tags
- **Limitations**: No hard namespace isolation; shared API server

**Dagster Cloud (2025-2026)**
- **Teams**: Group users with default deployment/code-location/branch-deployment roles
- **RBAC**: Fine-grained across platform (view-only, developer, admin per team)
- **Workspaces**: Logical grouping of code locations; scope access by workspace
- **Multi-deployment**: Multiple deployments per team; each with separate RBAC
- **Audit logs**: Track who did what and when
- **Limitations**: OSS Dagster has minimal RBAC; Cloud is required for teams/governance
- **Maturity note**: Governance features are newer; less battle-tested at scale than Airflow Astro

**Argo Workflows (2025)**
- **Namespace isolation**: Kubernetes namespaces are the primary tenancy boundary
- **RBAC**: Kubernetes native; ClusterRole/Role bindings per namespace
- **ArgoCD Projects**: Custom isolation layer across clusters/namespaces (if using ArgoCD)
- **Resource quotas**: Enforce per-namespace CPU/memory limits
- **Network policies**: Pod-level isolation; restrict cross-namespace traffic
- **Limitations**: Namespace boundaries not security boundaries by default; need defense-in-depth

### How Hydra Does It

In `scheduler/models/`, `scheduler/api/domain.py`, `scheduler/api/admin.py`, `worker/worker.py`:
- **Domain model**: Lightweight multi-tenancy via domain scoping (default: `prod`)
- **Tokens**: Two-tier auth: Admin token (global) + domain token (scoped to domain)
- **Domain-scoped APIs**: Most endpoints accept `x-domain` header or derive domain from token
- **Job isolation**: Jobs tagged by domain; workers filter by domain in Redis queue names
- **Worker ACL**: Redis ACL users per domain; worker auth via domain-scoped password
- **No RBAC**: No granular permissions (e.g., can't restrict user X to read-only on job Y)
- **No team/workspace concept**: Domains are singular; no hierarchy (team → domain → job)

### Gap Assessment & Recommendations

**Strengths:**
- ✅ Domain model is simple and effective for multi-tenant isolation
- ✅ Redis ACL per domain prevents cross-domain worker interference
- ✅ Job queue isolation (`job_queue:<domain>:pending`) enforces hard domain boundary
- ✅ Lightweight: no complex RBAC engine needed

**Gaps:**
1. **No role-based access** – All users with domain token have same permissions (can't enforce read-only)
2. **No team/workspace hierarchy** – Can't scope jobs to sub-teams within a domain
3. **No audit logs** – Can't track who submitted which job or changed what config
4. **No tag-based permissions** – Unlike Airflow; can't scope access by job tags
5. **Limited user concept** – Jobs have `user` field but it's metadata; not enforced at auth layer

**Recommendations:**
1. **Add optional RBAC layer (MEDIUM-HIGH)** → New `scheduler/models/rbac.py`: Define Role/Permission (read_jobs, write_jobs, read_runs, kill_runs, admin). Domain has roles; users assigned to roles. API checks token + role before granting access. Start with 3 roles: Viewer (read-only), Operator (read + execute), Admin (all). Benefit: Aligns with Airflow/Dagster model; enables data governance compliance.
2. **Extend domain hierarchy (MEDIUM, future)** → Add optional `team` field to domain or create Team → Domain relationship in Mongo. Domain tokens inherit team permissions. Benefit: Supports org structure (eng-team → data-domain → data-job); enables cross-team dashboards.
3. **Add audit logging (MEDIUM)** → New `scheduler/models/audit_log.py`: Log all mutating API calls (create/update/delete job, kill run, rotate credentials). Store in Mongo `audit_logs` collection with timestamp, user, action, resource, before/after state. Expose `GET /audit/logs?domain=X&action=create_job`. Benefit: Compliance, forensics, security monitoring.
4. **Support job tag-based access control (LOW-MEDIUM, future)** → When RBAC is in place, allow role assignment to tag (e.g., "analytics team can manage all jobs tagged 'analytics'"). Benefit: Scales access control for large teams.

### Current Domain Model Strengths

Hydra's current simple domain model is actually appropriate for many use cases and doesn't need to be replaced wholesale. The recommendation is to add RBAC *on top* of domains, not instead of them, allowing teams to opt into granular access control as needed.

---

## 7. CLI/GitOps Parity

### Investigation Status
*Starting...*

---

## 8. Naming/Terminology Standardization

### Investigation Status
*Starting...*

---

## Summary — Top 5 Priorities

*To be filled after investigation completion...*
