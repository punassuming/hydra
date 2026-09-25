# Hydra Jobs — Cross-Cutting Investigation Summary & Priority Roadmap

**Date:** 2026-09-25 (revised after independent validation + 3 additional investigations)

**Inputs:** 14 investigations, each with full detail in this directory:
`01-security.md`, `02-ai-integration.md`, `03-ux.md`, `04-ui-styling.md`,
`05-job-management.md`, `06-best-practices-comparison.md` (Dagster/Airflow/Argo),
`07-cicd-pipeline.md`, `08-worker-framework.md` (Python↔Go protocol),
`09-worker-implementations.md` (Python vs. Go quality), `10-worker-capabilities-cross-platform.md`,
`11-datastore-management.md` (Redis/MongoDB), `12-dependency-upgrades.md`,
`13-docker-compose.md`, `14-kubernetes-helm-kustomize.md`.

This document collates all findings into one prioritized backlog. Findings that surfaced
independently in multiple investigations (a strong signal) are called out explicitly.

## Verification history — read this before trusting any single line item

Every one of the first 11 reports went through a **second, independent validation pass** — a
fresh agent re-opened the cited source and re-derived each claim rather than trusting the
original. Confidence by report: **01-security 97.7%, 02-ai-integration 99.2%, 03-ux ~93%,
04-ui-styling 93%, 05-job-management 6/9 areas confirmed (2 real errors), 06-best-practices
19/21 external + 17/17 Hydra-code confirmed, 07-cicd-pipeline 95%, 08-worker-framework 71% (2
real errors), 09-worker-implementations 96% (1 real mixup), 10-worker-capabilities 33/34,
11-datastore-management 7/10 (2 real errors).** The three newest reports (12, 13, 14) were
spot-checked directly rather than run through a full second pass; one real error was found and
corrected in `13-docker-compose.md`.

**Real errors found and corrected, in order of consequence:**

1. **`09-worker-implementations.md`** falsely claimed the Go worker implements a `sensor`
   executor. Direct code inspection (`go-worker/internal/executor/executor.go`) confirms it does
   not — corrected to 7 types. Consistent with `08-worker-framework.md` and
   `05-job-management.md`, which got this right independently.
2. **`06-best-practices-comparison.md`** cited "Argo Workflows v2.7+, 2025-2026" (actual current:
   **v4.1.x**) and Airflow's DAG versioning as "AIP-36" (actually **AIP-66/AIP-65**) — stale
   citations from training-data recall instead of verified search. Corrected; the substantive
   comparisons were unaffected.
3. **`01-security.md`**'s "`google-generativeai` is old, bump to 0.50+" finding *understated* the
   risk: the SDK is fully **deprecated** past a removal deadline (June 24, 2026) already passed.
   Escalated to Tier 0 as a package-swap migration, not a version bump — see item 0 below.
4. **`05-job-management.md`**'s "no unified CLI exists" finding is **wrong** — `hydra-ctl`
   already exists (`cli/__main__.py`, registered in `pyproject.toml`) with 15+ subcommands
   covering everything the report said was missing. That recommendation is struck, not just
   downgraded.
5. **`05-job-management.md`** also claimed the Go worker is "missing impersonation/Kerberos
   support" — **wrong**; Go's `withImpersonation()`/`kerberosInit()` (confirmed directly in
   `go-worker/internal/executor/executor.go`) support both on Linux/Darwin, guarded the same way
   Python's is. AGENTS.md's blanket "Go worker: shell/http/external, no SQL/impersonation/
   Kerberos" line is now confirmed wrong on three counts (executor types, sensor, and
   impersonation/Kerberos) — see the Tier 3 doc-fix item.
6. **`08-worker-framework.md`** overstated a `startup_duration_ms` gap and invented a
   `WORKER_STATE` vs `INITIAL_STATE` env-var mismatch that doesn't exist (both workers use
   `WORKER_STATE`). Corrected; the report's actual top priorities (timing fields, protocol
   versioning) were unaffected.
7. **`11-datastore-management.md`** claimed `worker_ops:*` and `log_stream:*:history` are
   unbounded Redis growth risks — **wrong**, both are already LTRIM-bounded with TTLs
   (1000 entries/7-day and 400 entries/1-hour respectively). The report's actual top risk
   (`job_runs` in MongoDB, genuinely unbounded) is unaffected.
8. **`13-docker-compose.md`** originally recommended *adding* `version: "3.8"` to every compose
   file. Verified via WebSearch: this is backwards — the `version:` key has been obsolete since
   Compose V2 (2022+) and modern `docker compose` warns if it's present. Retracted; omitting it
   is already correct.

Three spot-checks on the dependency-upgrade report's most specific claims (`CVE-2026-26007`,
TypeScript 7.0's native Go compiler, Vite 8.0's Rolldown rewrite) confirmed accurate against live
search — that report's density of exact version numbers held up, unlike the Argo/Airflow case.

**Net effect on the roadmap below:** nothing in the original Tier 0/1 priority list was
invalidated by any of this. One Tier 2 item (unified CLI) is removed outright. Everything else
is either unaffected or gained a one-line correction.

---

## How to read this

Four tiers, roughly ordered by **(risk or value) ÷ (effort)**:

- **Tier 0 — Do now.** Small, contained fixes with outsized risk reduction. Most are single-digit
  hours of work.
- **Tier 1 — Near-term (days).** Real engineering, but scoped and high-value.
- **Tier 2 — Strategic (weeks).** Architectural investments that compound; sequence deliberately.
- **Tier 3 — Backlog.** Worth doing, not urgent.

---

## Tier 0 — Do now

| # | Finding | Source(s) | Effort |
|---|---|---|---|
| 0 | **`google-generativeai` SDK is fully deprecated, past its removal deadline (June 24, 2026)** — not a version bump, a package swap (`google-generativeai` → `google-genai`) + API rewrite of `_call_gemini()`. Gemini-backed AI features risk being already degraded or about to break. | `01-security.md` #1, `12-dependency-upgrades.md` (confirms independently) | Medium |
| 0b | **Go toolchain (`go-worker/go.mod`) targets Go 1.24, which is now end-of-life** — no further security patches from upstream. Bump the `go` directive to 1.26 and re-run CI. | `12-dependency-upgrades.md` | Low (1 line + CI run) |
| 1 | **Go worker leaks Git PATs to disk** — `.git/config` is never scrubbed after clone (Python worker does this; Go doesn't). Any process with cache-directory access can extract tokens. | `09-worker-implementations.md` #1 | Low (~1 hr) |
| 2 | **No timeout on LLM calls** — `scheduler/api/ai.py:114,129`. A hung Gemini/OpenAI call blocks the request indefinitely. | `02-ai-integration.md` #1, `01-security.md` (adjacent) | Trivial (~5 min) |
| 3 | **Zero MongoDB indexes exist** — `job_runs`/`job_definitions`/`credentials` queries do full collection scans. Independently flagged by **two separate investigations** as the top operational risk. | `05-job-management.md` #1, `11-datastore-management.md` #1 | Low (2-4 hrs) |
| 4 | **Go worker doesn't advertise `sensor` capability but could still receive sensor jobs** — silent dispatch failure. | `08-worker-framework.md` #2, `05-job-management.md` #3 | Low-Medium (2-4 hrs) |
| 5 | **Go worker's `run_end` events omit `total_run_ms`/`source_fetch_ms`/`env_prep_ms`** — breaks duration prediction/outlier detection for any job that ran on a Go worker. | `08-worker-framework.md` #1 | Low (1-2 hrs) |
| 6 | **Batch executor advertised on Windows without verifying `cmd.exe` exists** — one missing preflight check, same pattern already used for PowerShell/shell. | `10-worker-capabilities-cross-platform.md` #1 | Trivial (~10 lines) |
| 7 | **Admin token is root-equivalent with no audit trail** — intentional design, but undocumented as such and unlogged. | `01-security.md` #2 | Trivial (docs + a log line) |

**Why these first:** every one of these is a contained diff, several were flagged independently by
more than one investigation, and #1 is a genuine security bug, not a theoretical one.

---

## Tier 1 — Near-term (days)

| # | Finding | Source(s) | Effort |
|---|---|---|---|
| 8 | **Job definition versioning/audit trail** — no history of what a job's definition used to be. Called the single best "quick win" by **both** the job-management and best-practices investigations. | `05-job-management.md` #1, `06-best-practices-comparison.md` #2 | Low (1-2 days) |
| 9 | **MongoDB has no self-healing** — Redis has the excellent `redis_acl_reconciliation_loop`; Mongo has nothing equivalent. An outage requires a manual scheduler restart. | `11-datastore-management.md` #3 | Medium (6-8 hrs) |
| 10 | **`job_runs` grows unbounded, no retention policy** — no TTL/cleanup/archival. Flagged as a multi-terabyte risk after 1-2 years in production. | `11-datastore-management.md` #2, `05-job-management.md` (adjacent) | Medium (6-8 hrs) |
| 11 | **No registry-push CI workflow** — image builds are validate-only; real deployments require 100% manual build+push. Blocks any GitOps story. | `07-cicd-pipeline.md` #1 | Medium (~50 lines) |
| 12 | **Non-conventional commits silently skip release-please** — no `commitlint` gate at PR time; versions/changelog entries can go missing unnoticed. | `07-cicd-pipeline.md` #2 | Low (~10 lines) |
| 13 | **Prompt injection surface in AI custom-question field** — user input interpolated into LLM prompts unescaped, both UI (`FailureInsight.tsx:195`) and backend (`ai.py:226`). | `01-security.md` #3, `02-ai-integration.md` #2 | Low (length cap + system-prompt guard) |
| 14 | **RunInspector has no retry/backfill action buttons** — failed run → view logs → close drawer → navigate elsewhere → retry is 4+ clicks; the AI analysis panel is also below the fold, requiring scrolling past logs first. | `03-ux.md` #3 | Low-Medium (UI additions; API calls already exist) |
| 15 | **Accessibility: 1 `aria-label` across the entire UI, zero alt text, status colors are color-only** — real gap for screen-reader and colorblind users, independently re-derived and confirmed exact during validation. | `04-ui-styling.md` #1-2 | Medium (systematic but mechanical) |
| 16 | **No explicit worker protocol version field** — the Redis wire contract between Python/Go workers is entirely implicit; drift bugs (items 4, 5, and the exit-code mismatch below) are already proof this happens silently. | `08-worker-framework.md` #4 | Medium (3-5 hrs + a CI compatibility test) |
| 17 | **Timeout exit-code mismatch: Python returns 124, Go returns 137** — mixed worker pools misinterpret each other's timeouts if a job's completion logic parses exit codes. | `09-worker-implementations.md` #2 | Medium (change + test update) |
| 18 | **Add SLA-miss and retry-storm canned investigations** — cheap (~20 lines each), high operator value, closes a gap vs. Airflow/Dagster that Hydra already has the data for. | `02-ai-integration.md` #3 | Low (~40 lines total) |
| 19 | **`docker-compose.dev.yml`'s `environment:` block replaces, not merges, the base file's** — `REDIS_URL`/`MONGO_URL` defaults could silently vanish in dev mode if not separately set in `.env`. | `13-docker-compose.md` #1 | Low (5-10 lines) |
| 20 | **Helm chart has no `values.schema.json`** — misconfigurations (`maxConcurrency: 0`, invalid domain names) are caught at runtime, not at `helm lint`/`helm install` time. | `14-kubernetes-helm-kustomize.md` #1 | Low (~150-line schema file) |

---

## Tier 2 — Strategic (weeks)

| # | Finding | Source(s) | Effort |
|---|---|---|---|
| 21 | **No multi-step DAG support within a single job** — N sequential steps require N separate jobs today, hiding workflow structure. The single biggest structural gap vs. Airflow/Dagster/Argo. | `06-best-practices-comparison.md` #1 | High (`steps` field + scheduler sequencing) |
| 22 | **No GitOps reconciliation loop** — `hydra-apply.py` is a manual/CI-triggered script, not a continuously-reconciling watcher like Argo CD. | `06-best-practices-comparison.md` #3 | Medium-High |
| 23 | **Job-form complexity (30+ fields at once) and fragmented history views** — the create→monitor→debug→retry workflow crosses 3+ pages and loses context on tab switches. | `03-ux.md` #1-2 | Medium |
| 24 | **Theme system fragmentation** — three parallel color systems (CSS variables, React `ThemeContext`, ~14 hardcoded hex values) creating drift risk. | `04-ui-styling.md` #3 | Medium-High (mechanical migration) |
| 25 | **Retry strategy has no exponential backoff or dead-letter queue** — fixed delay only; permanently-failed jobs vanish with no audit trail. | `05-job-management.md` #2, `06-best-practices-comparison.md` #4 | Medium |
| 26 | **Docker layer caching missing in `python-ci.yml`** — rebuilds images from scratch every PR despite `container-images.yml` already having the GHA-cache recipe to copy. | `07-cicd-pipeline.md` #3 | Low (~15 lines, listed here only because it's paired with #11's workflow work) |
| 27 | **Go worker: no panic recovery, fixed 1s Redis-reconnect retry (vs. Python's 2-60s backoff)** — a single unhandled goroutine panic kills the whole process. | `09-worker-implementations.md` #3-4 | Low-Medium |
| 28 | **Acceptance tests (executor matrix, domain isolation, failover) never run in CI**, only opt-in locally. Add as a release-PR-gated job. | `07-cicd-pipeline.md` #5 | Medium |
| 29 | **OpenAI SDK is 2 majors behind (1.12 → 3.19), with breaking client-API changes** — bundle this migration with the (mandatory) Gemini SDK swap in item 0, since both touch the same file (`scheduler/api/ai.py`) and both need full LLM-call regression testing anyway. | `12-dependency-upgrades.md` | High |
| 30 | **Frontend toolchain is 1-2 majors behind across the board: React 18→19, Vite 6→8, TypeScript 5.4→7.0, Ant Design 5→6** — each individually verified as a real, current release (not stale training data). Sequence as one coordinated upgrade (Vite/TypeScript build-toolchain first, then React, then Ant Design last since it has the deepest component-API surface), not four independent PRs. | `12-dependency-upgrades.md` | High (multi-week, phased) |
| 31 | **Redis clients are behind with wire-protocol-level changes: Python `redis-py` 5→8 (RESP3 default), Go `go-redis` v9.5→v9.22** — needs integration testing for pub/sub and pipelining, not just a version bump. | `12-dependency-upgrades.md` | Medium-High |
| 32 | **`croniter` is 4 majors behind (2.0.5→6.2.4) with an incompatible cron-grammar rewrite** — every stored cron expression needs re-validation after upgrading. | `12-dependency-upgrades.md` | Medium |
| 33 | **Operational scripts (`verify-live.sh`, `verify-worker-boundary.sh`) hardcode the Compose project name** (`hydra-worker-1`) — breaks silently under a custom `-p` project name or the multi-pool naming scheme. | `13-docker-compose.md` #3 | Medium |
| 34 | **Helm chart has no `PodDisruptionBudget`** — node drain/eviction can force ungraceful downtime on the single-pod scheduler/Redis/MongoDB. | `14-kubernetes-helm-kustomize.md` #2 | Low-Medium |

---

## Tier 3 — Backlog (real, not urgent)

- RBAC layer on top of the domain model (`06-best-practices-comparison.md` #5) — domains work well today; add roles when multi-team access control is actually needed.
- Cross-platform capability-detection test coverage (mock `platform.system()` for Windows/macOS) (`10-worker-capabilities-cross-platform.md` #3).
- Datastore observability: split `/health` into per-datastore status, add Prometheus metrics (`11-datastore-management.md` #4).
- Backup lifecycle management — retention/rotation policy, automated restore-test Routine (`11-datastore-management.md` #5).
- Auto-fix retry suggestions, natural-language run-history query (`02-ai-integration.md` #4-5) — genuinely valuable, but big-bet features, not quick wins.
- **Update AGENTS.md's Go worker description — now confirmed wrong on three separate points**: it says Go supports "shell/http/external... no SQL executor or impersonation/Kerberos." In reality Go also implements batch/python/powershell/sql (7 types total), *and* does support impersonation/Kerberos on Linux/Darwin (validation-confirmed against `go-worker/internal/executor/executor.go`). The only executor type genuinely Python-only is `sensor`. Doc-only, trivial, but do it as one pass covering all three corrections together.
- Terminology glossary (Job/Run/Executor ↔ DAG/Task Instance/Operator) to ease onboarding for engineers coming from Airflow/Dagster (`06-best-practices-comparison.md` #8).
- Deployment-type auto-detection gaps (Podman/Kubernetes/WSL misclassified as "standalone") — cosmetic only, no functional impact (`10-worker-capabilities-cross-platform.md` #4).
- Routine minor/patch dependency bumps with no breaking changes: `pydantic` 2.9→2.13, `pymongo` 4.10→4.18, `SQLAlchemy` 2.0.36→2.0.54/2.1.0, `fastapi` 0.115→0.141, `uvicorn` 0.30→0.52, `pytest` 8.3→9.1, `cryptography`≥46.0.5→≥49.0.0 (already-fixed CVE, current constraint permits it), `@tanstack/react-query` 5.24→5.103. None urgent individually; batch into a routine maintenance pass. (`12-dependency-upgrades.md`)
- Docker Compose modernization: `profiles:` to replace the 7-file-per-topology pattern, `develop.watch` to replace the manual dev-volume + `uvicorn --reload` combo, `include:` to compose the common file-combinations into named presets. Real but optional; the current multi-file approach already works. (`13-docker-compose.md`)
- Add timeouts to `verify-live.sh`/`verify-worker-boundary.sh`'s curl/socket calls so a hung service can't block the script indefinitely (`13-docker-compose.md` #4); write a `deploy/compose/README.md` documenting the operational scripts' secret-file/permission prerequisites (`13-docker-compose.md` #5).
- Optional Helm `NetworkPolicy` template to restrict component-to-component traffic — not needed for home-lab, worth having for production overlays (`14-kubernetes-helm-kustomize.md` #5).

### Resolved, no action needed
- **Kustomize:** evaluated and explicitly rejected. Helm's `values.yaml` arrays already cover every multi-domain/multi-pool customization case Hydra has; layering Kustomize on top would create two competing customization mechanisms for the same chart — a recognized anti-pattern. If a deployment team ever needs cluster-specific patches Helm truly can't express, the documented fallback is a post-render pipe (`helm template | kustomize build -`), not a parallel overlay system. (`14-kubernetes-helm-kustomize.md`)
- **Compose `version:` key:** confirmed the codebase is already doing the right thing by omitting it (obsolete since Compose V2). No action.

---

## Cross-cutting patterns worth naming

A few things showed up **independently, from investigations that had no visibility into each
other's work** — that convergence is itself a signal:

1. **MongoDB indexing** was flagged as the top operational risk by both the job-management and
   datastore-management investigations, arrived at from completely different angles (API design
   review vs. datastore operations review). Do this one first among the "boring but important"
   items.
2. **Go worker drift from Python worker is the most persistent theme in this entire investigation
   effort** — it now shows up across *four* separate investigations (framework/protocol,
   implementation comparison, capabilities/cross-platform, job-management) and, after
   validation, spans: missing sensor support, missing timing fields, timeout exit-code mismatch,
   Git PAT hygiene, no panic recovery, and *three separate points* where AGENTS.md's own
   description of Go's capabilities is simply wrong (executor-type count, sensor, and
   impersonation/Kerberos). None of the individual fixes are hard, but together they say Go-worker
   parity needs one dedicated pass — code and docs together — before recommending mixed
   Python+Go pools for anything beyond simple shell/HTTP jobs.
3. **"No self-healing for Mongo, unlike Redis's ACL reconciliation loop"** appeared as a direct
   comparison in the datastore investigation and as an implicit gap in the job-management one.
   The existing Redis pattern (`scheduler/scheduler.py:533-555`) is explicitly called "gold
   standard" and is the template to copy.
4. **Job versioning** was independently proposed as the best quick win by both the job-management
   investigation and the Dagster/Airflow/Argo comparison — different motivations (audit trail vs.
   industry parity), same recommendation.
5. **Every investigation that touched the AI/security boundary** (security, AI integration) found
   the same prompt-injection surface in the custom-question field — worth fixing once, not twice.
6. **Dependency/tooling claims that turned out to be wrong were, without exception, external-tool
   claims** (Argo's version, Airflow's AIP number, the Compose `version:` key's status) —
   never claims about Hydra's own source code, which held up at 93-99% across every report once
   independently re-derived. The lesson generalizes: trust this whole effort's read of Hydra's
   codebase; verify anything it says about a third-party tool's current state before acting on it.

## Suggested first sprint

If picking a starting slice rather than working strictly top-to-bottom: **all of Tier 0 (items
0-7, all small and independently shippable) plus item 8 (job versioning) and item 13 (prompt
injection).** Together they close the one real security bug (Go PAT leak), the one urgent
dependency migration (Gemini SDK) plus a one-line EOL fix (Go toolchain), the one
universally-agreed quick win (job versioning), and the reliability gaps that would otherwise bite
anyone running a mixed Python/Go worker pool today.
