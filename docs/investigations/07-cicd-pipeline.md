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

**Coverage Assessment:**

✓ **Python matrix:** 3.11 and 3.13 × Ubuntu, macOS, Windows (6 jobs, `fail-fast: false`). Aligns with AGENTS.md requirement.

✓ **Lint (ruff):** Single `lint` job, `uv run ruff check .` on Python 3.13. Fast (~30 sec).

✓ **Go worker tests:** Separate `go-test` job, reads Go version from `go-worker/go.mod`, runs `go test ./...` with Go module cache. ~20 sec.

✓ **Helm lint + template:** 5 assertions in a single `helm` job:
  - `helm lint --strict`
  - Default values template
  - Separated scheduler + ingress template
  - Multi-domain worker pools template
  - demoMode + extraEnv regression (Python YAML parser checks env/envFrom structure)
  - UI container port 8080 regression (Python parser validates Service/Deployment/probes agree)
  
  → Well-structured regression checks; good architectural coverage.

✓ **Docker image builds:** 4-image matrix (scheduler/worker/ui/go-worker) in `docker-build` job. Uses `docker build` (not buildx). Does **not** use Docker layer cache in python-ci.yml (only in container-images.yml). Estimated ~2-3 min per image with fresh layers.

✓ **Full-stack Compose smoke test:** `end-to-end` job using `.github/compose.e2e.yml` overlay. Runs `tests/test_end_to_end.py`. Includes service log dump on failure and cleanup. ~2-4 min.

✓ **Cypress browser journey:** `ui-browser` job, waits up to 60s for UI (30 polls × 2s), runs `cypress run --spec cypress/e2e/operator-auth.cy.ts`. Includes service logs on failure. ~4-6 min.

**Caching:**
- Python: `uv` lockfile (`uv.lock`) locked at version `0.5.13` pinned in install step; no explicit pip/uv cache action (relies on GHA runner's built-in uv cache). **Opportunity:** could use `actions/setup-python@v5` with `cache: "pip"` or explicit uv cache action for faster runs on `main`.
- npm/Node: `actions/setup-node@v4` with `cache: "npm"` on both `ui` and `ui-browser` jobs. Good.
- Docker: `docker-build` in python-ci.yml doesn't use `docker/build-push-action` or layer cache. **Gap:** container-images.yml uses `cache-from: type=gha` and `cache-to: type=gha,mode=max`, but python-ci.yml rebuilds layers every time. Could copy GHA cache strategy to python-ci for speed.
- Go: `actions/setup-go@v5` with `cache-dependency-path: go-worker/go.sum`. Good.

**Parallelization & Speed:**
- Total CI matrix: 6 Python × OS + lint (serial) + helm + ui + docker (4 serial) + go + e2e + ui-browser = **broad but not optimal parallelization**.
- Slack: python-ci `test` job (slowest: 5 min on Windows) can run in parallel with helm/lint/ui/docker/go/e2e/ui-browser (all start immediately).
- E2E + UI-browser run Docker Compose, which may contend for resources on smaller runners (no resource limits in workflows).
- **Wall-clock estimate:** ~7-8 minutes (6 Python jobs × 5 min worst-case on Windows + e2e/ui-browser in parallel = bottleneck is Python tests).

**Issues Found:**
- Inconsistent Docker caching strategy: python-ci.yml (no cache) vs container-images.yml (GHA cache). Recommend standardizing to use `docker/build-push-action` + GHA cache in both.
- E2E and UI-browser start full Docker Compose stacks in parallel — if both run on same runner, they may contend (redis port 6379, mongo 27017, scheduler 8000, UI 5173). No explicit port management. Currently OK because they're the slowest jobs and run last, but fragile.
- No integration test for the CLI (`hydra-ctl`) — only E2E covers API directly.

---

## 3. Release Automation (release-please)
*Investigating: version bump driving across pyproject.toml/ui/package.json/Chart.yaml, Conventional Commit gating, config drift*

**Configuration Review:**

✓ **Conventional Commit gating:** `release-please-config.json` defines changelog sections for all types (feat/fix/perf/docs/chore/refactor/test/build/ci/revert/deps). Types that bump version: `fix:` (patch), `feat:` (minor, pre-1.0), `fix!:`/`feat!:`/`BREAKING CHANGE:` (major, post-1.0). Config aligns with CONTRIBUTING.md, section "Commit messages (Conventional Commits)".

✓ **Pre-1.0 behavior:** `bump-minor-pre-major: true` in config, `bump-patch-for-minor-pre-major: false`. This means `feat:` bumps minor (0.1.0 → 0.2.0), not major. Correct per CONTRIBUTING.md.

✓ **Version tracking:** Release-please manages versions in:
  - `pyproject.toml` (jsonpath `$.project.version`)
  - `ui/package.json` (jsonpath `$.version`)
  - `deploy/helm/hydra/Chart.yaml` (jsonpath `$.version`)
  - `deploy/helm/hydra/values.yaml` (8 image tag entries: scheduler, ui, workers[0], workers[1], domainSeed)
  - `.release-please-manifest.json` (current version tracker)

✓ **Bootstrap SHA:** `bootstrap-sha: "25f3d0db173015a2defd6d39e1dddea3ab3adbce"` set; release-please won't open a release PR for commits before this point.

✓ **Changelog path:** `CHANGELOG.md` exists and should be maintained by release-please.

**Token Strategy:**
- Workflow prefers `RELEASE_PLEASE_TOKEN` (fine-grained PAT with `contents: write` + `pull requests: write`), falls back to `GITHUB_TOKEN` if not set.
- Fallback works but with gap: release-please-opened PRs won't trigger other workflows (python-ci.yml). Per CONTRIBUTING.md, optional PAT closes this gap. Not set up by default.
- **Risk:** If `RELEASE_PLEASE_TOKEN` is not configured, release PRs skip CI checks before merge. Real risk if merge-commit policy is enforced and each commit is scanned.

**Sync Issues — Potential Drift:**
- `values.yaml` has 8 image tag entries spread across multiple fields. If release-please config is missing any, images will drift from the app version. Let me verify the config covers all:
  - Config lists 8 entries: ✓ `scheduler.image.tag`, `ui.image.tag`, `workers[0].image.tag`, `workers[1].image.tag`, `domainSeed.image.tag`.
  - But `workers[0]` and `workers[1]` are hardcoded indices. If Helm values add a third worker, the new entry won't auto-bump. **Drift risk:** Worker pool additions require manual config.json update.

**Merge Commit Policy Impact:**
- Per AGENTS.md, PRs merge with merge commit (not squash), so each commit reaching main is scanned individually.
- Release-please opens a single PR (e.g., `chore(main): release 0.2.0`) with multiple commits (one per version-bump file + CHANGELOG). When that PR merges, **all commits are scanned**, but only if the merge commit's message itself follows Conventional Commits. The release PR title is `chore(main): release X.Y.Z` — the merge commit message will likely inherit that, which means it won't bump versions (chore: doesn't bump). OK, because the release is already cut by the workflow on the next push.

**Current Version:** `.release-please-manifest.json` shows version `0.1.0`. Aligned with `pyproject.toml`, `ui/package.json`, `Chart.yaml`. Good.

**Issues Found:**
- No explicit CI gate ensuring release PRs are tested before merge (missing `RELEASE_PLEASE_TOKEN` setup — documented as optional, but important).
- Helm `values.yaml` image tag tracking via hardcoded indices (`workers[0]`, `workers[1]`) — brittle if worker array grows.
- No visible GitHub Branch Protection rule enforcement of required status checks (can't infer from workflows alone).

---

## 4. Container Image Workflow
*Investigating: 4-image build validation, push policy, Helm chart integration for real deployments*

**Build Validation (container-images.yml):**

✓ **Scope:** Builds all 4 deployable images (scheduler, worker, go-worker, ui) on push to main + changes to source dirs/pyproject.toml/uv.lock. Manual trigger via `workflow_dispatch` with optional version input.

✓ **Versioning:** Reads version from `pyproject.toml` at build time; no hardcoded version. Matches release-please's single source of truth.

✓ **Modern tooling:** Uses `docker/build-push-action@v6` with buildx, GHA layer cache (`cache-from: type=gha` + `cache-to: type=gha,mode=max`), provenance metadata, and SBOM generation. Good security posture.

**Critical Gap — No Push:**

❌ **`push: false`** — workflow only validates builds; **images are NOT pushed to any registry**. Per line 58 in container-images.yml. This is intentional per AGENTS.md ("build-validation only, no registry push").

**Deployment Story:**

Per Helm chart README (`deploy/helm/hydra/README.md`):
- **Default workflow:** Build images locally, load onto cluster nodes (k3s, kind, minikube, or containerd SSH), then `helm install`.
- **Alternative:** Push to registry, set `imagePullPolicy: Always`, override `image.repository`/`tag`, add `imagePullSecrets` if private.
- **Documentation:** Clear and prescriptive; steps provided for all major K8s distributions.

**Issue — No Registry Push in CI/CD:**

- The Helm chart is designed for "cluster-local" image loading (no registry), which is perfect for home-lab/staging.
- **For production or GitOps:** Need to push images to a registry. Currently, this is **100% manual**:
  1. Developer builds images locally (`docker build -f scheduler/Dockerfile -t hydra-scheduler:0.1.0 .`)
  2. Developer pushes: `docker push <registry>/hydra-scheduler:0.1.0` (4 times)
  3. Developer updates Helm values to override `image.repository` and `imagePullPolicy`.
  4. Deploy via GitOps or manual `helm upgrade`.
  
  There is **no workflow** automating steps 2–3.

**Recommendation:** Add a registry-push job (conditionally on version bump):
- Trigger on release-please's release tag (e.g., `v0.2.0`).
- Build and push to GHCR (GitHub Container Registry) or Docker Hub.
- Update Helm values or tag release artifacts with registry URLs.

**Current State Assessment:**
- ✓ Build validation is solid and runs on every push.
- ✓ Helm chart documentation is clear for home-lab deployments.
- ❌ No CI/CD path to production registries.
- ❌ Unclear how to deploy to a "real" cluster with GitOps (e.g., ArgoCD pulling from registry).

---

## 5. Branch Protection & Merge Policy
*Investigating: merge-commit enforcement, required checks, review requirements per CONTRIBUTING.md*

**Merge Policy per CONTRIBUTING.md:**

✓ **Merge Commit:** CONTRIBUTING.md explicitly states: "This repo merges PRs with a merge commit (not squash), so each individual commit reaching `main` is scanned on its own — write every commit message as if it stands alone."

✓ **Conventional Commits Required:** Commit messages must follow Conventional Commits (`<type>[scope]: <description>`). Enforced by release-please parsing, not by branch protection pre-check.

✓ **PR Template:** `.github/pull_request_template.md` includes checklist (tests pass, style, no unrelated changes, documentation updated).

**GitHub Branch Protection Settings:**

Cannot be read directly from the local repo, but inferred from workflow design:
- **Assumed Required Status Checks:**
  - `test` job (one per Python version × OS)
  - `lint` job
  - `helm` job
  - `ui` job (type-check, tests, build)
  - `docker-build` job (4 images)
  - `go-test` job
  - `end-to-end` job
  - `ui-browser` job
  
  These are not explicitly listed in workflows as `required`, but python-ci.yml structure suggests they should be required checks on `main`.

- **Assumed Dismissed/Not Required:**
  - `release-please.yml` job is release-only and would create circular dependencies if required (release PR merge triggers workflow that opens next release PR).

**Gaps & Observations:**

❌ **No explicit `required-status-checks` configuration in workflows:** The workflows don't declare which jobs must pass. This suggests branch protection is configured manually in GitHub UI, not as code. **Risk:** Settings can drift from documentation without a clear audit trail.

❌ **Conventional Commit enforcement not pre-commit:** The workflows don't block non-conventional commits; release-please just ignores them (they appear in merges but don't bump versions/changelog). A commit like `update worker` would merge without triggering a release PR, then vanish from the changelog. This can cause silent versioning gaps.

⚠️ **Review requirements unknown:** Workflows don't specify number of approvals, code owner review, or restrictions. PR template suggests manual review discipline, but no automation enforces it.

**Recommended Improvements:**
1. Add a pre-commit or merge-time check (e.g., `commitlint` action) to reject non-conventional commits at PR open time.
2. Document branch protection settings in a `.github/branch-protection.md` or GitHub's native protection settings UI (non-code but visible to collaborators).
3. Consider requiring specific job groups as status checks (e.g., "unit tests" = all Python matrix jobs, "integration" = E2E + UI browser).

---

## 6. Secrets & Permissions
*Investigating: workflow permission scopes, secret usage hygiene, supply-chain risks*

**Workflow Permissions:**

✓ **Minimal Scoping (most jobs):**
  - `python-ci.yml` jobs (test, lint, helm, ui, docker-build, go-test): `permissions: { contents: read }`
  - `end-to-end`, `ui-browser`: No explicit permissions (inherit GitHub's defaults, typically read).
  - `container-images.yml`: `permissions: { contents: read }`
  
  All read-only. Correct principle of least privilege.

⚠️ **Broad Permissions (release automation):**
  - `release-please.yml`: `permissions: { contents: write, pull-requests: write }`
  
  Necessary for opening/merging release PRs, but broad. Risk: if workflow is compromised, attacker can modify main branch. Mitigated by `release-please-action` being official (googleapis) and maintained.

**Secret Usage:**

✓ **Minimal Secret Exposure:**
  - Only secret referenced: `RELEASE_PLEASE_TOKEN` (optional fallback to `GITHUB_TOKEN`).
  - Not printed to logs (used only as token input).
  - No third-party API keys (Gemini, OpenAI) in workflows — those are set at runtime only (scheduler/worker Dockerfile `ENV` or `.env`).

✓ **E2E Environment:**
  - `HYDRA_E2E=1`, `HYDRA_E2E_DOMAIN=ci`, `HYDRA_E2E_TOKEN=ci-domain-token` are test-only, not sensitive.

✓ **No Secrets in Docker Build Context:**
  - Dockerfiles don't embed API keys or credentials; they come from runtime environment.

**Supply-Chain Risks:**

✓ **Action Versions Pinned:**
  - `actions/checkout@v4` (minor version, not latest).
  - `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/setup-go@v5`.
  - `docker/setup-buildx-action@v3`, `docker/build-push-action@v6`.
  - `googleapis/release-please-action@v4`.
  
  All pinned to major versions (good for stability). Could be more aggressive (pin to patch versions like `@v4.2.1`) but current approach is reasonable.

✓ **Third-Party Dependencies:**
  - `release-please` is official googleapis project (well-maintained).
  - Docker actions are official (docker org).
  - No experimental/unverified actions.

⚠️ **Token Fallback Risk (release-please):**
  - Fallback to `GITHUB_TOKEN` works but has known limitation: doesn't trigger other workflows on PR open. If `RELEASE_PLEASE_TOKEN` is not configured, release PRs skip CI checks before merge.
  - Per CONTRIBUTING.md, this gap is documented but optional to fix. A compromised workflow could open a bad release PR; main branch CI ensures it's caught on merge, but requires the full CI matrix to pass on the release PR merge commit.
  - **Recommendation:** Set `RELEASE_PLEASE_TOKEN` (fine-grained PAT with minimal scopes).

⚠️ **No OIDC Token Usage:**
  - Workflows use explicit secrets, not OIDC federation to cloud providers. Fine for GitHub-scoped actions, but if pushing to external registries (future), consider OIDC for better security.

**Overall Assessment:**
- Permissions are well-scoped for a read-only CI system.
- Secrets are minimal and never printed.
- Token strategy for release automation is documented but partially incomplete (no `RELEASE_PLEASE_TOKEN` configured by default).

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

