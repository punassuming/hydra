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

### Investigation Status
*Starting...*

---

## 5. Sensors & Event-Driven Triggering

### Investigation Status
*Starting...*

---

## 6. Multi-Tenancy & RBAC Standardization

### Investigation Status
*Starting...*

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
