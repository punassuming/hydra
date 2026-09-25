# CI/CD Pipeline Investigation

**Date:** 2026-09-25  
**Status:** Live running log — findings appended as investigation progresses

---

## 1. Workflow Inventory
*Investigating: list every workflow, triggers, jobs/matrix, and runtime*

**Three workflows found:**

### a) `python-ci.yml` (`.github/workflows/python-ci.yml`)
- **Triggers:** `push` to main/master, `pull_request` against main/master
- **Jobs (9 total):**
  1. `test` — Matrix: 3 OS × 2 Python versions (6 × runners) = 6 parallel jobs. ~3-5 min each (uv sync + pytest).
  2. `lint` — Single job (Ubuntu, Python 3.13), runs ruff. ~30 sec.
  3. `helm` — Single job, runs 5 helm lint/template checks (default, separated+ingress, multi-domain, demoMode+extraEnv regression, UI port regression). ~1-2 min.
  4. `ui` — Single job (Ubuntu, Node 20), npm ci + tsc + vitest + build. ~2-3 min, includes Docker cache.
  5. `docker-build` — Matrix: 4 services (scheduler/worker/ui/go-worker). ~2-3 min each with Docker layer cache.
  6. `go-test` — Single job, `go test ./...` on go-worker. ~20 sec.
  7. `end-to-end` — Full-stack smoke test (Docker Compose up, pytest `tests/test_end_to_end.py`). ~2-4 min.
  8. `ui-browser` — Cypress operator journey (full stack + 30s UI wait + cypress run). ~4-6 min.
- **Concurrency:** `fail-fast: false` on multi-job matrices → all matrix cells run even if one fails.
- **Permissions:** Mostly `contents: read` (good), but `release-please.yml` has `contents: write` + `pull-requests: write`.

### b) `release-please.yml` (`.github/workflows/release-please.yml`)
- **Triggers:** `push` to `main` only (not `main` or `master` like python-ci).
- **Jobs:** Single job — runs `googleapis/release-please-action@v4` with fallback token logic (prefers `RELEASE_PLEASE_TOKEN` secret, falls back to `GITHUB_TOKEN`).
- **Permissions:** `contents: write`, `pull-requests: write`.
- **Frequency:** Runs on every push to main. On PR merge, opens/updates a standing release PR; if that PR is merged, tags the release and publishes GitHub Release notes.

### c) `container-images.yml` (`.github/workflows/container-images.yml`)
- **Triggers:** `push` to `main` on changes to `scheduler/`, `worker/`, `go-worker/`, `ui/`, `pyproject.toml`, `uv.lock`, or the workflow itself. Also `workflow_dispatch` with optional version input.
- **Jobs:** Single job with matrix over 4 images (scheduler/worker/go-worker/ui). Reads version from `pyproject.toml`, builds with Docker buildx, uses GHA cache. **`push: false`** — no registry push; this is build-validation only.
- **Permissions:** `contents: read`.

**Findings:**
- No workflow for pushing images to a registry (DockerHub, GHCR, etc.). The Helm chart README documents a local build + load-onto-cluster approach; no CI/CD integration for registry pushes. Real deployments must build and push images manually.
- No branch-protection settings visible in workflows (no `required-status-checks` or auto-merge blocks).
- `release-please.yml` triggers only on `main`, while `python-ci.yml` triggers on `main` or `master` — asymmetry, though likely not an issue if only `main` is active.

---

## 2. Python CI Coverage
*Investigating: matrix (3.11/3.13 × Linux/macOS/Windows), lint, Go worker tests, Helm, Docker, E2E, Cypress*

(Pending)

---

## 3. Release Automation (release-please)
*Investigating: version bump driving across pyproject.toml/ui/package.json/Chart.yaml, Conventional Commit gating, config drift*

(Pending)

---

## 4. Container Image Workflow
*Investigating: 4-image build validation, push policy, Helm chart integration for real deployments*

(Pending)

---

## 5. Branch Protection & Merge Policy
*Investigating: merge-commit enforcement, required checks, review requirements per CONTRIBUTING.md*

(Pending)

---

## 6. Secrets & Permissions
*Investigating: workflow permission scopes, secret usage hygiene, supply-chain risks*

(Pending)

---

## 7. Test-in-CI vs Test-Locally Gaps
*Investigating: acceptance test opt-in, what should/should not run in CI*

(Pending)

---

## 8. Deployment CD Story
*Investigating: is there any deployment automation, or is that fully manual? GitOps story?*

(Pending)

---

## 9. Developer Feedback Loop Speed
*Investigating: wall-clock time for full PR-check suite to go green*

(Pending)

---

## Summary — Top 5 Priorities
*(To be filled once investigation completes)*

