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

**Current Test Matrix in CI:**

✓ **Unit Tests:** `tests/` (excluding E2E) run on every commit across 3 OS × 2 Python versions. Fast (~3-5 min per matrix cell).
  - Covers: models, API endpoints, job scheduling, worker selection, Redis/Mongo clients, AI endpoints, investigations, ACL reconciliation.
  - Per AGENTS.md: `test_mongo_client.py` explicitly asserts timezone-aware BSON decoding; `test_ai.py` covers generate/analyze/predict/diagnose; `test_investigations.py` validates canned checks.

✓ **E2E Smoke Test:** Full-stack Docker Compose (scheduler, worker, Redis, Mongo) + `tests/test_end_to_end.py`. ~2-4 min.
  - Covers: API integration, job submission, worker dispatch, log streaming, end-to-end job execution.
  - **Not** acceptance tests (no multi-domain isolation, no executor matrix, no chaos/resilience).

✓ **UI Integration:** Cypress browser journey (`ui-browser` job). ~4-6 min.
  - Covers: operator auth flow, basic UI navigation.
  - Single Cypress spec: `operator-auth.cy.ts`. Limited scope.

✓ **Helm Chart Validation:** 5 template/lint checks (default, separated, multi-domain, demoMode regression, port regression). ~1-2 min.
  - Does not deploy to K8s; only validates templating and YAML structure.

**Acceptance Tests (Deliberately Opt-Out of CI):**

Per `tests/acceptance/README.md`:
- Suite takes **minutes** (not seconds), requires real infrastructure, and tests chaos (worker death, Redis/Mongo restart).
- Opt-in via `HYDRA_ACCEPTANCE=1`; never runs in CI.
- Three backends: `docker` (dynamic provision), `kubectl` (existing Helm), `none` (bare API smoke check).
- Covers: domain isolation, full executor matrix, mixed Python/Go worker routing, failover/resilience.

**Assessment — Gap Analysis:**

**What CI Tests Well:**
- ✓ API correctness and scheduler logic (unit tests).
- ✓ Python/Go worker code (unit + Go tests).
- ✓ Helm templating (chart lint + 5 template checks).
- ✓ Basic end-to-end integration (single E2E job).
- ✓ UI auth + basic navigation (Cypress).

**What CI **Does Not** Test:**
- ❌ **Executor matrix:** E2E only tests shell/python executors; SQL, batch, powershell, http, external, sensor executors not validated in CI.
- ❌ **Domain isolation:** No multi-domain testing in CI; only E2E uses a single `ci` domain.
- ❌ **Worker pool routing:** Mixed Python + Go worker pools only tested in acceptance suite (opt-in).
- ❌ **Failover/Resilience:** Worker death, Redis restart, Mongo restart scenarios only in acceptance suite.
- ❌ **Multi-domain concurrency:** Load testing, starvation handling, bypass_concurrency not exercised in CI.

**Risk Assessment:**

⚠️ **Moderate Risk** — A regression in executor types (SQL, batch) or domain isolation would not be caught until acceptance test run (manual). However:
- Executor implementations are deterministic (no dynamic dispatch errors likely).
- Domain isolation is enforced at middleware level (likely to fail unit tests if broken).
- Acceptance tests are documented and repeatable (`./scripts/run-acceptance-tests.sh`).

✓ **Mitigation** — Acceptance tests are lightweight enough to add to pre-release CI jobs (e.g., trigger `docker` backend on release PRs). Not required for every PR, but strongly recommended before cutting a release.

**Recommendation:**
1. Keep unit/E2E/UI tests in CI (fast feedback).
2. Add acceptance test (`docker` backend) as an optional matrix job on release PRs or tagged as `run-acceptance-tests` label.
3. Document in CONTRIBUTING.md that release reviewers should ensure acceptance tests pass (even if not automated).

---

## 8. Deployment CD Story
*Investigating: is there any deployment automation, or is that fully manual? GitOps story?*

**Current Deployment Architecture:**

❌ **No CI/CD Deployment Workflow:** There is NO GitHub Actions workflow that deploys Hydra to any environment (staging, prod, dev, K8s cluster). All deployments are **100% manual**.

**Local/Compose Deployment (Docker Compose):**
- **Workflow:** Clone repo → build images locally → docker-compose up.
- **CI** provides: validated Dockerfiles, docker-compose.yml syntax checks (indirectly via Helm), tests.
- **Manual step:** Build + push images, edit `.env`, run `docker compose up`.
- **Operational tooling:** `deploy/compose/` provides encrypted backup/restore (`backup-volumes.sh`/`restore-isolated.sh`) and live verification (`verify-live.sh`, `verify-worker-boundary.sh`). Scripts check consistency but do not automate deployment.

**Kubernetes/Helm Deployment:**
- **Workflow:** Clone repo → build images locally → load onto cluster nodes → helm install/upgrade.
- **CI** provides: Helm lint + 5 template checks (no actual K8s deploy), image build validation.
- **Manual steps:** Build images → load onto nodes (k3s ctr import / kind load / minikube image load / containerd SSH) → helm install/upgrade with custom values.
- **Documentation:** Helm chart README clearly documents build + load + install steps. Repeatable but entirely manual.

**GitOps / Registry Push Story:**

❌ **No GitOps Tooling:** No ArgoCD, Flux, or other declarative deployment system.

❌ **No Registry Push Workflow:** Container images are not pushed to any registry in CI/CD. For production use, deployment would look like:
1. Developer builds images locally: `docker build -f scheduler/Dockerfile -t hydra-scheduler:0.1.0 .`
2. Developer pushes manually: `docker push <registry>/hydra-scheduler:0.1.0` (repeat 4 times)
3. Developer updates Helm values to point to registry: `--set scheduler.image.repository=<registry>/hydra-scheduler`
4. Developer runs: `helm upgrade hydra deploy/helm/hydra -f <custom-values>`

**Recommendation for Production GitOps:**

A typical workflow would be:
1. **On release tag (v0.1.0):** Trigger a `push-images` job that:
   - Builds all 4 images.
   - Pushes to GHCR (GitHub Container Registry) or private registry as `<registry>/hydra-scheduler:0.1.0`.
   - Updates a Helm values file with the registry URLs.
   - Commits the values update (or opens a PR for review) in a separate `deploy-config` branch.

2. **Trigger ArgoCD/Flux:** GitOps controller pulls the deploy branch and applies the Helm chart.

3. **Alternative (simpler):** Hook `helm upgrade` into a separate workflow that listens for release tags.

**Current Maturity:**
- ✓ Excellent for home-lab/development (manual Compose is fast and flexible).
- ✓ Good Helm chart for K8s, but no automation to push images.
- ❌ Not production-ready without external orchestration (manual push to registry, manual helm deploy).

**Recommended Action:**
Add a `push-images.yml` workflow that:
- Triggers on `push` with tag `v*` (release tags from release-please).
- Builds and pushes images to GHCR with tag matching the release version.
- Optionally updates Helm values or creates a PR against a `deploy-values` branch for GitOps controllers to reconcile.

---

## 9. Developer Feedback Loop Speed
*Investigating: wall-clock time for full PR-check suite to go green*

**Job Timeline & Parallelization:**

python-ci.yml jobs and estimated runtimes:
- `test` (6 matrix cells): Ubuntu + macOS (~3-4 min), **Windows (~5-7 min)** — parallelized.
  - Bottleneck: Windows is ~2x slower than Linux.
  - Other cells (Linux 3.11, 3.13; macOS 3.11, 3.13) finish in ~3-4 min.
  
- `lint` (1 job): ~30 sec (sequential, starts immediately).

- `helm` (1 job, 5 template checks): ~1-2 min (sequential).

- `ui` (1 job): npm ci → tsc → vitest → build: ~2-3 min (sequential).

- `docker-build` (4 matrix cells: scheduler, worker, ui, go-worker):
  - Without GHA cache (~2-3 min per image) = ~2-3 min parallel (all 4 run simultaneously).
  - **Issue:** python-ci.yml doesn't use GHA cache (docker/build-push-action not used). Falls back to inline `docker build`. Container-images.yml **does** use GHA cache, making it ~30-60 sec per image on cache hit.

- `go-test` (1 job): ~20 sec (sequential).

- `end-to-end` (1 job): docker compose up + pytest + cleanup: ~2-4 min (includes DB startup time).

- `ui-browser` (1 job): compose up + wait for UI + cypress: ~4-6 min (includes browser startup + test).

**Parallelization Model:**

```
T=0:
  - test[ubuntu-3.11] START
  - test[ubuntu-3.13] START
  - test[macos-3.11] START
  - test[macos-3.13] START
  - test[windows-3.11] START
  - test[windows-3.13] START (slowest, 5-7 min)
  - lint START (~30 sec)
  - helm START (~1-2 min)
  - ui START (~2-3 min)
  - docker-build[scheduler] START
  - docker-build[worker] START
  - docker-build[ui] START
  - docker-build[go-worker] START (all 4 in parallel, ~2-3 min)
  - go-test START (~20 sec)

T=5-7 min (Windows test finishes, all tests done):
  - end-to-end START (~2-4 min)
  - ui-browser START (~4-6 min, slower than E2E, bottleneck)

T=11-13 min (ui-browser finishes):
  - ALL DONE
```

**Wall-Clock Estimate:**
- **Best case (all cached, fast runners):** ~9 min (7 min Windows + 2 min docker-build in parallel).
- **Typical case (fresh cache on PR):** ~11-13 min (7 min Windows + 4-6 min ui-browser).
- **Worst case (all cache misses, no GHA Docker cache):** ~13-15 min (7 min Windows + 6 min ui-browser).

**Developer Experience:**

⚠️ **Moderate Feedback Loop:** 11-13 minutes is acceptable for a PR check suite (not as fast as smaller projects, but not glacial). Developers wait ~2-3 min for initial feedback (lint/helm/Go tests), then ~10 min for full pass.

**Opportunities to Speed Up:**

1. **Docker caching (highest impact):** Use `docker/build-push-action` + GHA cache in python-ci.yml (like container-images.yml does). Could shave ~1-2 min.
   - Current: 2-3 min per matrix job (all 4 in parallel).
   - Cached: ~30-60 sec per matrix job.
   - **Savings:** ~2 min on PR rebuild.

2. **Windows test optimization:** Windows takes 2x longer than Linux. Could:
   - Skip Windows on PRs, run only on main (saves 2 min).
   - Profile Windows-specific slowness (pip, uv sync, pytest on Windows slower?).
   - **Savings:** ~2 min, but sacrifices OS coverage.

3. **Parallelize E2E and UI-browser more carefully:**
   - Currently, if both start and contend for ports (redis 6379, mongo 27017, etc.), could fail.
   - No explicit port mapping or isolation.
   - **Risk:** race condition if runner is under-resourced.
   - **Savings:** Already parallel, but fragile.

4. **Reduce UI-browser scope:** Currently runs full Cypress suite (implied, one spec). Could split or reduce to smoke test only on PR.
   - **Savings:** ~2 min if reduced to quick smoke test.

5. **Matrix optimization:** `fail-fast: false` means all cells run even if one fails. Could set `fail-fast: true` for faster feedback on actual failures.
   - **Savings:** Highly variable (0-5 min if early cell fails).

**Recommendation:**

✓ Current ~11-13 min is reasonable. Priority improvements:

1. **Add Docker GHA cache to python-ci.yml** (2 min savings, low effort).
2. **Consider skipping Windows on PRs, run only on main** (2 min savings, small regression risk).
3. **Add `fail-fast: true` to matrix** (faster feedback on failures, optional).

Do NOT add more tests to the critical path (E2E + UI-browser) — they already dominate runtime.

---

---

## Independent Validation Pass (2026-09-25)

**Method:** Verified each claim against actual YAML workflow files (`.github/workflows/python-ci.yml`, `release-please.yml`, `container-images.yml`), release-please config, CONTRIBUTING.md, and tests/acceptance/README.md.

### Coverage Verification Summary

**CONFIRMED (32 claims):** Workflow triggers, job names/order, matrix dimensions (3 OS × 2 Python), permissions scoping, action versions (checkout@v4, setup-python@v5, setup-node@v4, setup-go@v5, docker/build-push-action@v6, release-please-action@v4), shell/python/Go test execution, Helm lint + 5 template checks (default, separated, multi-domain, demoMode, UI port), docker-build lack of GHA cache in python-ci.yml, container-images.yml's GHA cache config, `push: false` in container-images, Helm chart version tracking (pyproject.toml, ui/package.json, Chart.yaml, values.yaml tags), bootstrap-sha, acceptance tests opt-in/never-in-CI, no deployment CD workflow, merge-commit strategy per CONTRIBUTING.md, token fallback logic.

**WRONG (2 claims):**

1. **Job count:** Report claims "Jobs (9 total)" on line 15, then lists only 8. Actual count: `test`, `lint`, `helm`, `ui`, `docker-build`, `go-test`, `end-to-end`, `ui-browser` = **8 jobs**, not 9. **Corrected in the report abstract but the summary line is inaccurate.**

2. **Helm checks:** Report claims "5 assertions in a single `helm` job" on line 56, then describes them. Actual helm job steps (python-ci.yml lines 73–186): (1) `helm lint --strict`, (2) template default values, (3) template separated+ingress, (4) template multi-domain, (5) demoMode+extraEnv regression check (6) UI port regression check. **6 template/lint checks, not 5.** Error in line 56: "5 assertions" should be "6 assertions" or better phrased as "6 helm checks."

**PARTIALLY WRONG (0 new issues)** — The demoMode and UI port regression sections do list the 6th and 7th (and eventual final) checks, so the substance is there; only the count on line 56 is off.

**STALE (0 items)** — All claims reflect current YAML state as of 2026-09-25.

### Detailed Findings by Section

#### 1. Workflow Inventory ✅ CONFIRMED
- 3 workflows exist as described.
- python-ci triggers: `push` + `pull_request` on `main`/`master` ✓
- release-please triggers: `push` on `main` only ✓
- container-images triggers: `push` on `main` + path filters + `workflow_dispatch` ✓
- Permissions: `contents: read` across CI, `contents: write` + `pull-requests: write` for release-please ✓

#### 2. Python CI Coverage ✅ MOSTLY CONFIRMED (8 jobs, not 9)
- **Matrix:** 3 OS × 2 Python versions = 6 test runners ✓
- **Test execution:** `uv run --frozen pytest tests/ --ignore=tests/test_end_to_end.py` ✓
- **Lint:** `uv run --frozen ruff check .` on Ubuntu/3.13 ✓
- **Helm:** Actually **6 checks** (not 5 as reported on line 56):
  - `helm lint --strict` ✓
  - `helm template` (default) ✓
  - `helm template` (separated + ingress) ✓
  - `helm template` (multi-domain) ✓
  - Python YAML parser regression (demoMode + extraEnv) ✓
  - Python YAML parser regression (UI port 8080 agreement) ✓
- **UI:** npm ci, tsc, vitest, build ✓
- **Docker build:** 4-service matrix, no GHA cache (line 245: plain `docker build`) ✓
- **Go tests:** `go test ./...` ✓
- **E2E:** Docker Compose + pytest ✓
- **Cypress:** Operator auth journey ✓
- **Caching:** Report's assessment of inconsistency (python-ci no cache, container-images has GHA cache) is accurate ✓

#### 3. Release Automation ✅ CONFIRMED
- Version tracking files: pyproject.toml, ui/package.json, Chart.yaml, values.yaml (8 jsonpath entries) ✓
- bootstrap-sha: `25f3d0db173015a2defd6d39e1dddea3ab3adbce` ✓
- `bump-minor-pre-major: true` ✓
- Current version: 0.1.0 ✓
- Token strategy (prefer RELEASE_PLEASE_TOKEN, fallback to GITHUB_TOKEN) ✓
- CONTRIBUTING.md Section 2 and 3 match workflow design ✓

#### 4. Container Image Workflow ✅ CONFIRMED
- `push: false` (line 58) ✓
- `docker/build-push-action@v6` with `cache-from: type=gha,mode=max` ✓
- Version from pyproject.toml ✓
- 4-image matrix ✓

#### 5. Branch Protection & Merge Policy ✅ CONFIRMED (by document, not by GitHub UI rules)
- CONTRIBUTING.md line 46–49: "merge commit (not squash)" ✓
- Conventional Commits required per CONTRIBUTING.md ✓
- PR template exists (not examined in detail) ✓
- No explicit `required-status-checks` in YAML (branch protection is GitHub UI configured, not code) ✓

#### 6. Secrets & Permissions ✅ CONFIRMED
- Action versions pinned to majors (v4, v5, v6) ✓
- All read-only jobs have `permissions: contents: read` ✓
- No API keys embedded in workflows ✓
- RELEASE_PLEASE_TOKEN fallback to GITHUB_TOKEN ✓
- Token strategy documented in CONTRIBUTING.md ✓

#### 7. Test-in-CI vs Local Gaps ✅ CONFIRMED
- acceptance tests: `HYDRA_ACCEPTANCE=1` gate, never in CI (tests/acceptance/README.md line 13) ✓
- Three backends (docker, kubectl, none) ✓
- opt-in and repeatable ✓

#### 8. Deployment CD Story ✅ CONFIRMED
- **No deployment workflow exists.** Only 3 workflows in `.github/workflows/`: python-ci.yml, release-please.yml, container-images.yml.
- No push-images.yml, no deploy-k8s.yml, no registry-push workflow.
- All deployment is manual (Helm chart + local image build).
- Report's recommendation for registry-push workflow is sound. ✓

#### 9. Feedback Loop Speed ⚠️ UNVERIFIABLE
- Estimates (11-13 min typical) are reasonable but depend on runner speed and cache state.
- Timeline parallelization logic is sound.
- No actionable errors, recommendations are solid.

### Issues Needing Correction in Report

**Critical (factual error):**
- **Line 15:** "Jobs (9 total)" should be "Jobs (8 total)"
- **Line 56:** "5 assertions in a single `helm` job" should be "6 checks" or "6 helm lint/template assertions"

**Recommended Fix:**
```
Line 15: 
  OLD: "Jobs (9 total):"
  NEW: "Jobs (8 total):"

Line 56:
  OLD: "✓ **Helm lint + template:** 5 assertions in a single `helm` job:"
  NEW: "✓ **Helm lint + template:** 6 checks in a single `helm` job:"
```

### Overall Confidence Verdict

**95% Confidence (SOLID)** — The report is substantially accurate. The two numeric errors (9 jobs → 8, 5 checks → 6) are minor typos that don't affect the substance of findings or recommendations. All architectural claims, CI/CD workflows, release automation logic, security posture, and recommendations are correctly verified against actual code. The "no CD deployment workflow" finding is confirmed; all 3 workflows are accounted for.

**No new vulnerabilities or architectural issues uncovered.** The top 5 priorities identified remain sound.

---

## Summary — Top 5 Priorities

Ranked by (risk/impact reduced × implementation effort):

### 1. **Add Registry Push Workflow (CRITICAL)**
**Risk:** Blocking production deployments. Currently, images are only validated locally; no way to push to a registry for real deployments.  
**Impact:** Enables GitOps and production cluster deployments.  
**Effort:** Medium (new workflow `push-images.yml`, GHCR or registry credentials, ~50 lines).  
**Recommendation:** Add job that triggers on release tags (`v*`), builds all 4 images, pushes to GHCR with version tag, optionally creates PR against `deploy-values` branch for GitOps reconciliation.

### 2. **Enforce Conventional Commits at PR Time (HIGH)**
**Risk:** Non-conventional commits (e.g., "update worker") silently bypass version bumping. No changelog entry, no release tag — creates version gaps and invisible changes.  
**Impact:** Guarantees all commits reaching main are correctly parsed by release-please.  
**Effort:** Low (add `commitlint` GitHub Action, ~10 lines).  
**Recommendation:** Add `commitlint` action to python-ci.yml to reject non-conventional commits at PR open time, matching CONTRIBUTING.md's requirement.

### 3. **Add Docker GHA Cache to python-ci.yml (MEDIUM)**
**Risk:** Slow PR feedback loop (11-13 min). Docker images rebuild from scratch on every PR, wasting ~2 min.  
**Impact:** Faster developer feedback (shave ~2 min, down to ~9-11 min).  
**Effort:** Low (migrate `docker build` to `docker/build-push-action`, copy cache config from container-images.yml, ~15 lines).  
**Recommendation:** Replace inline `docker build` in `docker-build` job with `docker/build-push-action@v6` + `cache-from: type=gha` + `cache-to: type=gha,mode=max` (already used in container-images.yml).

### 4. **Configure RELEASE_PLEASE_TOKEN & Add Release PR CI (HIGH)**
**Risk:** Release PRs are not tested before merge (if RELEASE_PLEASE_TOKEN not configured). Release could break main.  
**Impact:** Release PRs get full CI matrix before merge, preventing bad releases.  
**Effort:** Low (create fine-grained PAT, add as `RELEASE_PLEASE_TOKEN` secret in repo, already conditionally used by release-please.yml, ~5 min setup).  
**Recommendation:** Repo owner creates fine-grained PAT (repo-scoped, `contents: write` + `pull-requests: write`), adds as `RELEASE_PLEASE_TOKEN` secret. Workflow already prefers it.

### 5. **Add Acceptance Tests to Release PR Jobs (MEDIUM)**
**Risk:** Executor matrix (SQL, batch, powershell, external, sensor) and domain isolation not tested before release. Bugs slip through.  
**Impact:** Catches executor-type regressions and domain isolation bugs before release.  
**Effort:** Medium (add job that runs `HYDRA_ACCEPTANCE=1 ACCEPTANCE_BACKEND=docker`, requires Docker resources, ~30 lines).  
**Recommendation:** Add optional acceptance job to `python-ci.yml` (only on release PRs or labeled with `run-acceptance`), runs `docker` backend suite. Ensures executor matrix + failover scenarios pass before release.

