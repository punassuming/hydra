# Hydra Jobs — Cross-Cutting Investigation Summary & Priority Roadmap

**Date:** 2026-09-25
**Inputs:** 11 independent investigations (security, AI integration, UX, UI styling, job
management capability, Dagster/Airflow/Argo best-practices comparison, CI/CD pipeline, worker
framework/protocol, Python-vs-Go worker implementation, worker capabilities & cross-platform
support, Redis/MongoDB management practices) — full detail in `01-security.md` through
`11-datastore-management.md` in this directory.

This document collates all findings into one prioritized backlog. Findings that surfaced
independently in multiple investigations (a strong signal) are called out explicitly.

**Post-hoc verification pass (2026-09-25):** before finalizing, every investigation was spot-checked
against the actual source and, for external claims, against live web search. Two reports required
correction (see the `> Correction` notes inside `06-best-practices-comparison.md` and
`09-worker-implementations.md`): a fabricated version citation for Argo Workflows and a wrong AIP
number for Airflow's DAG versioning (substance unaffected either way), and a factual error claiming
the Go worker implements a `sensor` executor (it does not — confirmed by direct code inspection,
consistent with two *other* independent investigations that got this right). One finding was
significantly **escalated**, not just corrected: the "outdated `google-generativeai` dependency"
item in the security report was upgraded from a low-priority version bump to a high-priority
migration once WebSearch confirmed the SDK is fully deprecated past its removal deadline — see
Tier 0, item 0 below.

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
| 0 | **`google-generativeai` SDK is fully deprecated, past its removal deadline (June 24, 2026)** — not a version bump, a package swap (`google-generativeai` → `google-genai`) + API rewrite of `_call_gemini()`. Gemini-backed AI features risk being already degraded or about to break. *Escalated during verification — originally filed as a routine "upgrade when convenient" note.* | `01-security.md` #1 (corrected) | Medium (SDK swap + rewrite `_call_gemini`, re-test) |
| 1 | **Go worker leaks Git PATs to disk** — `.git/config` is never scrubbed after clone (Python worker does this; Go doesn't). Any process with cache-directory access can extract tokens. | `09-worker-implementations.md` #1 | Low (~1 hr) |
| 2 | **No timeout on LLM calls** — `scheduler/api/ai.py:114,129`. A hung Gemini/OpenAI call blocks the request indefinitely. | `02-ai-integration.md` #1, `01-security.md` (adjacent) | Trivial (~5 min) |
| 3 | **Zero MongoDB indexes exist** — `job_runs`/`job_definitions`/`credentials` queries do full collection scans. Independently flagged by **two separate investigations** as the top operational risk. | `05-job-management.md` #1, `11-datastore-management.md` #1 | Low (2-4 hrs) |
| 4 | **Go worker doesn't advertise `sensor` capability but could still receive sensor jobs** — silent dispatch failure. | `08-worker-framework.md` #2, `05-job-management.md` #3 | Low-Medium (2-4 hrs) |
| 5 | **Go worker's `run_end` events omit `total_run_ms`/`source_fetch_ms`/`env_prep_ms`** — breaks duration prediction/outlier detection for any job that ran on a Go worker. | `08-worker-framework.md` #1 | Low (1-2 hrs) |
| 6 | **Batch executor advertised on Windows without verifying `cmd.exe` exists** — one missing preflight check, same pattern already used for PowerShell/shell. | `10-worker-capabilities-cross-platform.md` #1 | Trivial (~10 lines) |
| 7 | **Admin token is root-equivalent with no audit trail** — intentional design, but undocumented as such and unlogged. | `01-security.md` #1 | Trivial (docs + a log line) |

**Why these first:** every one of these is a contained diff, several were flagged independently by
more than one investigation (indices, Go worker gaps), and #1 is a genuine security bug, not a
theoretical one.

---

## Tier 1 — Near-term (days)

| # | Finding | Source(s) | Effort |
|---|---|---|---|
| 8 | **Job definition versioning/audit trail** — no history of what a job's definition used to be. Called the single best "quick win" by **both** the job-management and best-practices investigations. | `05-job-management.md` #1, `06-best-practices-comparison.md` #2 | Low (1-2 days) |
| 9 | **MongoDB has no self-healing** — Redis has the excellent `redis_acl_reconciliation_loop`; Mongo has nothing equivalent. An outage requires a manual scheduler restart. | `11-datastore-management.md` #3 | Medium (6-8 hrs) |
| 10 | **`job_runs` grows unbounded, no retention policy** — no TTL/cleanup/archival. Flagged as a multi-terabyte risk after 1-2 years in production. | `11-datastore-management.md` #2, `05-job-management.md` (adjacent) | Medium (6-8 hrs) |
| 11 | **No registry-push CI workflow** — image builds are validate-only; real deployments require 100% manual build+push. Blocks any GitOps story. | `07-cicd-pipeline.md` #1 | Medium (~50 lines) |
| 12 | **Non-conventional commits silently skip release-please** — no `commitlint` gate at PR time; versions/changelog entries can go missing unnoticed. | `07-cicd-pipeline.md` #2 | Low (~10 lines) |
| 13 | **Prompt injection surface in AI custom-question field** — user input interpolated into LLM prompts unescaped, both UI (`FailureInsight.tsx:195`) and backend (`ai.py:226`). | `01-security.md` #2, `02-ai-integration.md` #2 | Low (length cap + system-prompt guard) |
| 14 | **RunInspector has no retry/backfill action buttons** — failed run → view logs → close drawer → navigate elsewhere → retry is 4+ clicks; the AI analysis panel is also below the fold, requiring scrolling past logs first. | `03-ux.md` #3 | Low-Medium (UI additions; API calls already exist) |
| 15 | **Accessibility: 1 `aria-label` across the entire UI, zero alt text, status colors are color-only** — real gap for screen-reader and colorblind users. | `04-ui-styling.md` #1-2 | Medium (systematic but mechanical) |
| 16 | **No explicit worker protocol version field** — the Redis wire contract between Python/Go workers is entirely implicit; three separate drift bugs already exist as proof (items 4, 5, and Go's timeout-exit-code mismatch below). | `08-worker-framework.md` #4 | Medium (3-5 hrs + a CI compatibility test) |
| 17 | **Timeout exit-code mismatch: Python returns 124, Go returns 137** — mixed worker pools misinterpret each other's timeouts if a job's completion logic parses exit codes. | `09-worker-implementations.md` #2 | Medium (change + test update) |
| 18 | **Add SLA-miss and retry-storm canned investigations** — cheap (~20 lines each), high operator value, closes a gap vs. Airflow/Dagster that Hydra already has the data for. | `02-ai-integration.md` #3 | Low (~40 lines total) |

---

## Tier 2 — Strategic (weeks)

| # | Finding | Source(s) | Effort |
|---|---|---|---|
| 19 | **No multi-step DAG support within a single job** — N sequential steps require N separate jobs today, hiding workflow structure. The single biggest structural gap vs. Airflow/Dagster/Argo. | `06-best-practices-comparison.md` #1 | High (`steps` field + scheduler sequencing) |
| 20 | **No GitOps reconciliation loop** — `hydra-apply.py` is a manual/CI-triggered script, not a continuously-reconciling watcher like Argo CD. | `06-best-practices-comparison.md` #3 | Medium-High |
| 21 | **Job-form complexity (30+ fields at once) and fragmented history views** — the create→monitor→debug→retry workflow crosses 3+ pages and loses context on tab switches. | `03-ux.md` #1-2 | Medium |
| 22 | **Theme system fragmentation** — three parallel color systems (CSS variables, React `ThemeContext`, ~14 hardcoded hex values) creating drift risk. | `04-ui-styling.md` #3 | Medium-High (mechanical migration) |
| 23 | **No unified operator CLI** — `hydra-apply.py` + 6+ bash scripts + raw API calls, no single `hydra-ctl job/run/worker` surface. *(Note: `hydra-ctl` already exists per AGENTS.md with several subcommands — treat this as "extend," not "build from scratch.")* | `05-job-management.md` #3 | Medium (3-5 days) |
| 24 | **Retry strategy has no exponential backoff or dead-letter queue** — fixed delay only; permanently-failed jobs vanish with no audit trail. | `05-job-management.md` #2, `06-best-practices-comparison.md` #4 | Medium |
| 25 | **Docker layer caching missing in `python-ci.yml`** — rebuilds images from scratch every PR despite `container-images.yml` already having the GHA-cache recipe to copy. | `07-cicd-pipeline.md` #3 | Low (~15 lines, listed here only because it's paired with #11's workflow work) |
| 26 | **Go worker: no panic recovery, fixed 1s Redis-reconnect retry (vs. Python's 2-60s backoff)** — a single unhandled goroutine panic kills the whole process. | `09-worker-implementations.md` #3-4 | Low-Medium |
| 27 | **Acceptance tests (executor matrix, domain isolation, failover) never run in CI**, only opt-in locally — real but currently mitigated by their being deterministic/well-isolated. Add as a release-PR-gated job. | `07-cicd-pipeline.md` #5 | Medium |

---

## Tier 3 — Backlog (real, not urgent)

- RBAC layer on top of the domain model (`06-best-practices-comparison.md` #5) — domains work well today; add roles when multi-team access control is actually needed.
- Cross-platform capability-detection test coverage (mock `platform.system()` for Windows/macOS) (`10-worker-capabilities-cross-platform.md` #3).
- Datastore observability: split `/health` into per-datastore status, add Prometheus metrics (`11-datastore-management.md` #4).
- Backup lifecycle management — retention/rotation policy, automated restore-test Routine (`11-datastore-management.md` #5).
- Auto-fix retry suggestions, natural-language run-history query (`02-ai-integration.md` #4-5) — genuinely valuable, but big-bet features, not quick wins.
- Update AGENTS.md — it understates the Go worker's actual executor coverage (documents shell/http/external only; Go worker in fact also implements batch/python/powershell/sql — 7 types total, still genuinely lacking sensor and impersonation/Kerberos, unlike Python's full 8+2). Doc-only, trivial, but worth doing alongside item #4.
- Terminology glossary (Job/Run/Executor ↔ DAG/Task Instance/Operator) to ease onboarding for engineers coming from Airflow/Dagster (`06-best-practices-comparison.md` #8).
- Deployment-type auto-detection gaps (Podman/Kubernetes/WSL misclassified as "standalone") — cosmetic only, no functional impact (`10-worker-capabilities-cross-platform.md` #4).

---

## Cross-cutting patterns worth naming

A few things showed up **independently, from investigations that had no visibility into each
other's work** — that convergence is itself a signal:

1. **MongoDB indexing** was flagged as the top operational risk by both the job-management and
   datastore-management investigations, arrived at from completely different angles (API design
   review vs. datastore operations review). Do this one first among the "boring but important"
   items.
2. **Go worker drift from Python worker** is a recurring theme across three separate
   investigations (framework/protocol, implementation comparison, capabilities/cross-platform) —
   sensor capability, timing fields, timeout exit codes, PAT hygiene, docs accuracy. None of these
   are hard to fix individually, but together they say Go-worker parity needs a dedicated pass
   before recommending mixed Python+Go pools for anything beyond simple shell/HTTP jobs.
3. **"No self-healing for Mongo, unlike Redis's ACL reconciliation loop"** appeared as a direct
   comparison in the datastore investigation and as an implicit gap in the job-management one.
   The existing Redis pattern (`scheduler/scheduler.py:533-555`) is explicitly called "gold
   standard" and is the template to copy.
4. **Job versioning** was independently proposed as the best quick win by both the job-management
   investigation and the Dagster/Airflow/Argo comparison — different motivations (audit trail vs.
   industry parity), same recommendation.
5. **Every investigation that touched the AI/security boundary** (security, AI integration) found
   the same prompt-injection surface in the custom-question field — worth fixing once, not twice.

## Suggested first sprint

If picking a starting slice rather than working strictly top-to-bottom: **items 1-7 (Tier 0)
plus item 8 (job versioning) and item 13 (prompt injection)** — all small, independently shippable,
and together they close the one real security bug (Go PAT leak), the one universally-agreed
quick win (job versioning), and the reliability gaps that would otherwise bite anyone running a
mixed Python/Go worker pool today.
