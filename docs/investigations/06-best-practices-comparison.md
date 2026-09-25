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

### Investigation Status
*Starting...*

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
