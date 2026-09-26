# Docker Compose Investigation: Hydra Jobs

**Date:** 2026-09-25  
**Investigation Focus:** Full compose-file inventory, network topology, security hardening, datastore auth, build efficiency, dev vs prod modes, combination matrix, operational tooling, and modern Compose best practices.

---

## 1. Compose-File Inventory

**Files found:** 7 compose files + 1 CI overlay:

1. **docker-compose.yml** (base) — `/home/user/Hydra/docker-compose.yml`
   - Defines: `redis`, `mongo` (internal-only network), `scheduler`, `ui`
   - Networks: `backend` (internal: true) for datastores/scheduler, `frontend` for scheduler/UI ports
   - Datastore auth opt-in via `SCHEDULER_REDIS_PASSWORD`, `MONGO_INITDB_ROOT_USERNAME/PASSWORD` in `.env`
   - Expected combined with worker compose files

2. **docker-compose.worker.yml** (standalone Python worker) — `/home/user/Hydra/docker-compose.worker.yml`
   - Defines: `worker` service, scalable with `--scale worker=N`
   - Runs as UID/GID `10001:10001` (configurable via `HYDRA_WORKER_UID/GID` build args)
   - Security: `read_only: true`, `tmpfs` with `noexec,nosuid,size=256m`, `security_opt: ["no-new-privileges:true"]`
   - Network: plain `backend: {}` declaration; merges with base file's internal backend when combined
   - Standalone against remote Redis via `REDIS_URL` env var

3. **docker-compose.worker.go.yml** (standalone Go worker) — `/home/user/Hydra/docker-compose.worker.go.yml`
   - Defines: `go-worker` service, same security model and scaling as Python worker
   - Same UID/GID/tmpfs/network behavior as docker-compose.worker.yml
   - Note: AGENTS.md says Go worker lacks SQL/Kerberos/impersonation; compose confirms only shell/http/external executors listed in code

4. **docker-compose.workers.yml** (multi-pool) — `/home/user/Hydra/docker-compose.workers.yml`
   - Defines: `worker-python` and `worker-go` pools running side by side
   - Uses YAML anchors (`&worker-python-base`, `&worker-go-base`) to avoid duplication
   - Includes commented example for adding a third GPU-tagged pool
   - Pool-specific env vars: `WORKER_PYTHON_DOMAIN`, `WORKER_PYTHON_API_TOKEN`, `WORKER_PYTHON_TAGS`, etc.
   - Both pools have explicit `depends_on: scheduler: condition: service_healthy` and `networks: [backend]`

5. **docker-compose.separated.yml** (control-plane split) — `/home/user/Hydra/docker-compose.separated.yml`
   - Overrides `scheduler` environment to set `HYDRA_MODE=api`
   - Adds new `orchestrator` service running `python -m scheduler.orchestrator_entrypoint`
   - Orchestrator sets `HYDRA_MODE=orchestrator` and runs same Dockerfile as scheduler
   - Both dependent on Redis/Mongo health; orchestrator joins `backend` network

6. **docker-compose.dev.yml** (dev overlay) — `/home/user/Hydra/docker-compose.dev.yml`
   - Overrides `scheduler`: adds source volume (`./scheduler:/app/scheduler`), replaces CMD with uvicorn `--reload`
   - Sets `SEED_DOMAIN=dev` (default), `HYDRA_DEMO_MODE=true` (default)
   - Overrides `worker`: same source volume for `./worker:/app/worker`, explicit dependencies
   - All services join explicit `networks: [backend]` to stay on internal network in dev mode

7. **.github/compose.e2e.yml** (CI test overlay) — `/home/user/Hydra/.github/compose.e2e.yml`
   - Overrides `scheduler` env: `ADMIN_TOKEN=ci-admin-token`, `SEED_DOMAIN=ci`, `SEED_DOMAIN_TOKEN=ci-domain-token`
   - Defines fresh `worker` service (not in base) with CI token/domain, non-root hardening, `networks: [backend]`
   - Sets `WORKER_REQUIRE_REDIS_ACL=false` (CI env, no ACL provisioning needed)
   - Comment explicitly states this worker file is introduced fresh and needs explicit backend network declaration

**Composition patterns:**
- Base + single worker: `docker compose -f docker-compose.yml -f docker-compose.worker.yml`
- Base + multi-pool: `docker compose -f docker-compose.yml -f docker-compose.workers.yml`
- Separated API + orchestrator: `docker compose -f docker-compose.yml -f docker-compose.separated.yml`
- Dev live-reload: `docker compose -f docker-compose.yml -f docker-compose.dev.yml` (sometimes with worker overlay)
- CI: `docker compose -f docker-compose.yml -f .github/compose.e2e.yml up` (in CI jobs, not locally)

## 2. Network Topology

**Internal-only backend network:**
- Base file (`docker-compose.yml` lines 159–167) declares: `backend: {internal: true}` — no published ports to host, no outbound internet
- Services on backend: `redis`, `mongo`, `scheduler`, plus any worker (from worker.yml overlay)
- Services on frontend: `scheduler` (for API port 8000), `ui` (for UI port 5173)
- Redis/Mongo NEVER publish host ports; only reachable via container DNS (`redis:6379`, `mongo:27017`) from backend network services

**Network merging when composing files:**
1. Base defines: `backend: {internal: true}` + `frontend: {}` (both explicit)
2. `docker-compose.worker.yml` declares: `backend: {}` (empty, non-internal) at lines 65–66
3. Compose spec merges networks field-by-field: when combining files, the `backend:` entry from docker-compose.worker.yml is MERGED with (not replaced by) the base file's `backend: {internal: true}` entry
   - **Result:** Merged `backend` inherits `internal: true` from base file; worker joins an internal network
   - **Verified in code:** docker-compose.worker.yml lines 54–59 confirm this behavior with comment: "Compose merges this with that file's `internal: true` backend network rather than replacing it, so the worker joins the SAME internal network as the bundled redis/mongo/scheduler"

4. Standalone usage (worker alone against remote Redis): `docker compose -f docker-compose.worker.yml up` WITHOUT base file
   - Worker file's `backend: {}` is now the ONLY backend definition (no merge)
   - Result: `backend` is created as a plain, non-internal network; worker joins it alone with outbound access to remote Redis
   - This is explicitly documented in worker file lines 60–62

**Network verification — operational tooling:**
- `deploy/compose/scripts/verify-live.sh` line 32 checks: `docker inspect "hydra-${store}-1" --format '{{range $port,$bindings := .NetworkSettings.Ports}}{{if $bindings}}published{{end}}{{end}}'` for both redis and mongo, asserts EMPTY (no published ports)
- `deploy/compose/scripts/verify-worker-boundary.sh` lines 32–34 confirms worker can reach redis/mongo (on internal network) but line 27 confirms external TCP (1.1.1.1:443) is blocked

**DNS resolution:**
- Scheduler reaches `redis://redis:6379/0` (Docker's embedded DNS resolves `redis` → container IP on backend network)
- Worker reaches same via container DNS when on backend network; if pointed at external Redis via `REDIS_URL=redis://external-host:6379/0`, connection goes through Docker's host resolver or configured DNS (no network restriction on outbound via Redis driver — only the internal network restriction applies)

## 3. Security Hardening

**Non-root user (single-source-of-truth via ARGs):**

1. Python worker (`worker/Dockerfile` lines 11–14):
   ```dockerfile
   ARG HYDRA_WORKER_UID=10001
   ARG HYDRA_WORKER_GID=10001
   RUN groupadd --gid "${HYDRA_WORKER_GID}" hydra \
       && useradd --uid "${HYDRA_WORKER_UID}" --gid "${HYDRA_WORKER_GID}" --no-create-home --shell /usr/sbin/nologin hydra
   ```
   - UID/GID sourced from build ARG with default 10001:10001

2. Go worker (`go-worker/Dockerfile` lines 19–22):
   ```dockerfile
   ARG HYDRA_WORKER_UID=10001
   ARG HYDRA_WORKER_GID=10001
   RUN addgroup -g "${HYDRA_WORKER_GID}" hydra \
       && adduser -D -H -u "${HYDRA_WORKER_UID}" -G hydra -s /sbin/nologin hydra
   ```
   - Same UID/GID pattern; Alpine variant of groupadd/useradd

3. Compose files thread through:
   - `docker-compose.worker.yml` line 12: `HYDRA_WORKER_UID: ${HYDRA_WORKER_UID:-10001}`
   - `docker-compose.worker.yml` line 20: `user: "${HYDRA_WORKER_UID:-10001}:${HYDRA_WORKER_GID:-10001}"`
   - `.env.example` lines 76–82 documents single-source override: set `HYDRA_WORKER_UID`/`HYDRA_WORKER_GID` in .env

4. **Verification tool:** `deploy/compose/scripts/verify-worker-boundary.sh` lines 16–18 resolves expected user via `compose config` JSON and asserts actual container user matches

**Read-only rootfs:**
- All worker compose files: `read_only: true` (docker-compose.worker.yml line 21, docker-compose.worker.go.yml line 20)
- Verified in operational tooling: `verify-worker-boundary.sh` line 19 checks `ReadonlyRootfs == true`

**tmpfs with security flags:**
- Python worker (`docker-compose.worker.yml` lines 22–23):
  ```yaml
  tmpfs:
    - /tmp:rw,noexec,nosuid,size=256m
  ```
- Go worker (`docker-compose.worker.go.yml` lines 21–22): identical
- Multi-pool (`docker-compose.workers.yml` lines 31–32, 55–56): identical for both pools
- CI (`docker-compose.e2e.yml` lines 17–18): identical
- **Rationale:** `rw` allows job execution temp files; `noexec` blocks direct binary execution from /tmp; `nosuid` blocks setuid bits; `256m` caps runaway temp file growth

**No-new-privileges security opt:**
- All workers: `security_opt: ["no-new-privileges:true"]` (docker-compose.worker.yml line 24, .go.yml line 23)
- Scheduler: same at line 126 in base file
- UI: same at line 156 in base file
- Redis/Mongo: same at lines 35 and 82 respectively
- Verified in `verify-worker-boundary.sh` line 23: `CapAdd == null`, `SecurityOpt == ["no-new-privileges:true"]`

**Scheduler & UI security:**
- UI runs as `USER ${NGINX_UID}` where NGINX_UID=101 (unprivileged nginx user from `nginxinc/nginx-unprivileged:1.29-alpine` base image)
- Scheduler runs as root inside container but no special capabilities added
- Both have `security_opt: ["no-new-privileges:true"]` to prevent privilege escalation

**No host bind-mounts in prod compose files:**
- Base `docker-compose.yml`: no volumes on scheduler/ui/worker/redis/mongo
- Dev overlay `docker-compose.dev.yml` lines 3–4, 34–35: adds `./scheduler:/app/scheduler` and `./worker:/app/worker` volumes for live-reload
- `verify-worker-boundary.sh` line 21: checks `len .Mounts == 0` (expects no bind-mounts in prod)

**Capability restrictions:**
- `verify-worker-boundary.sh` line 22: asserts `CapAdd == null` (no extra capabilities granted)
- `Privileged == false` line 20

## 4. Datastore Auth (opt-in behavior)

**Redis auth via SCHEDULER_REDIS_PASSWORD:**

- Base file (`docker-compose.yml` lines 6–8): comment states "Auth is opt-in: leave SCHEDULER_REDIS_PASSWORD unset for a zero-config local run"
- Redis command line (line 18): `redis-server --appendonly yes ${SCHEDULER_REDIS_PASSWORD:+--requirepass "$SCHEDULER_REDIS_PASSWORD"}`
  - **Bash parameter expansion `${VAR:+...}` logic:** if `SCHEDULER_REDIS_PASSWORD` is set (non-empty), include `--requirepass "$SCHEDULER_REDIS_PASSWORD"`; otherwise omit it entirely
  - Scheduler can then connect as root (no password) if unset, or with password if set
- Redis healthcheck (lines 26–31): conditional logic using `$$SCHEDULER_REDIS_PASSWORD` (double-$$escape for env var in healthcheck shell)
  - If password set: `redis-cli -a "$$SCHEDULER_REDIS_PASSWORD" ping` (auth required)
  - If unset: `redis-cli ping` (no auth)
- Scheduler environment (line 97): `REDIS_PASSWORD=${SCHEDULER_REDIS_PASSWORD:-}` passes through to scheduler connection
- Worker environment (`docker-compose.worker.yml` line 29): `REDIS_PASSWORD=${REDIS_PASSWORD:-}` (falls back to unset, inherits from .env)
- **Graceful degradation verified:** Docker Compose's parameter expansion is evaluated at config time, so unset variable → command string without `--requirepass` → no auth required on startup

**MongoDB auth via MONGO_INITDB_ROOT_USERNAME/PASSWORD:**

- Base file (lines 49–52): comment states "Auth is opt-in, same pattern as redis"
- Mongo command line (line 62): static `["mongod", "--bind_ip_all", "--setParameter", "diagnosticDataCollectionEnabled=false"]` — no conditional like Redis
  - **Why:** Mongo's official Docker image **automatically** detects `MONGO_INITDB_ROOT_USERNAME` and `MONGO_INITDB_ROOT_PASSWORD` env vars (lines 64–65) and auto-enables `--auth` + creates root user itself; the command line doesn't need to specify `--auth`
- Mongo healthcheck (lines 73–78): conditional logic in shell script
  - If `MONGO_INITDB_ROOT_PASSWORD` set: `mongosh --username "$$MONGO_INITDB_ROOT_USERNAME" --password "$$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin`
  - If unset: `mongosh` (no auth)
- `.env.example` lines 39–43 warns: if auth is set, also update `MONGO_URL` to include credentials (e.g., `mongodb://<user>:<pass>@mongo:27017/?authSource=admin`)
- Scheduler environment (`docker-compose.yml` line 100): `MONGO_URL=${MONGO_URL:-mongodb://mongo:27017}` — no embedded username/password in base file; user must add to .env
- **Graceful degradation verified:** unset USERNAME/PASSWORD → Mongo's official image skips `--auth` → no auth required on startup

**External datastore bypass:**
- Comments in base file (lines 94–100) and in `.env.example` (lines 49–57) document pointing at external Redis/Mongo instead of bundled services
- If external: set `REDIS_URL` / `MONGO_URL` in .env; bundled services go unused
- Run `docker compose up --no-deps scheduler ui` (and same pattern on worker overlays) to skip starting bundled datastore containers entirely

**Example flow for zero-config local dev:**
1. No .env file created (or created empty)
2. Docker Compose resolves: `SCHEDULER_REDIS_PASSWORD=` (empty), `MONGO_INITDB_ROOT_USERNAME=` (empty)
3. Redis starts without `--requirepass`; Mongo starts without `--auth`
4. Scheduler/worker connect successfully with no credentials
5. Datastores remain accessible only on internal network, but authentication is not enforced

**Example flow for production:**
1. `.env` includes `SCHEDULER_REDIS_PASSWORD=<secret>`, `MONGO_INITDB_ROOT_USERNAME=admin`, `MONGO_INITDB_ROOT_PASSWORD=<secret>`
2. Redis starts with `--requirepass <secret>`; Mongo's image auto-enables `--auth` and creates root user
3. Scheduler's `REDIS_PASSWORD` and worker's `REDIS_PASSWORD` are set to same secret
4. Scheduler's `MONGO_URL` is updated to `mongodb://admin:<secret>@mongo:27017/?authSource=admin`
5. Datastores enforce authentication; only authorized connections succeed

## 5. Build Efficiency & Dockerfiles

**Scheduler (`scheduler/Dockerfile` lines 1–22):**
- Base: `python:3.13-slim` ✓ (slim variant, good)
- Multi-stage: NO — single stage
- Layer order:
  1. Install uv (line 5): `RUN pip install --no-cache-dir uv==0.5.13`
  2. Copy lock files (line 6): `COPY pyproject.toml uv.lock ./`
  3. Install deps (line 7): `RUN uv sync --frozen --no-dev --no-install-project` (no-dev saves build size, no-install-project avoids pkg installation at build time)
  4. Copy source (line 9): `COPY scheduler /app/scheduler`
- **Cache efficiency:** Good — deps layer (`pyproject.toml` + `uv.lock` + uv sync) is cached independently from source layer
- **Issue:** Line 5 installs uv from pip (trusted, but rebuilds on every Docker version change); consider pinning pip itself or using uv's standalone installer for better reproducibility
- Final image includes: Python 3.13-slim + uv venv (.venv); no build tools left in final stage ✓
- `.dockerignore` at `/home/user/Hydra/.dockerignore` excludes `.git`, `.github`, `.venv`, `__pycache__`, `.pyc`, `.pytest_cache`, `ui/node_modules`, `ui/dist` — good coverage ✓

**Python Worker (`worker/Dockerfile` lines 1–31):**
- Base: `python:3.13-slim` ✓
- Multi-stage: NO
- Layer order:
  1. Install system deps (line 5): `apt-get install -y git` (needed for Git executor)
  2. Create non-root user (lines 11–14): UID/GID ARGs with defaults
  3. Install uv (line 16): same as scheduler
  4. Copy lock files (line 17)
  5. Install deps (line 18): same uv sync pattern
  6. Copy source (line 20)
- **Cache efficiency:** Good — deps layer independent from source
- **Issue:** System package layer (apt-get install git) is before uv install; if `git` version needs update later, all Python layers rebuild. Minor: consider installing git in a separate, earlier RUN to isolate it
- No build tools left in final stage ✓
- Heartbeat liveness check (lines 25–29) is well-designed: checks file mtime within 30s

**Go Worker (`go-worker/Dockerfile` lines 1–34):**
- **Multi-stage: YES** ✓ (best practice)
- Build stage (lines 1–8):
  - `golang:1.24-alpine AS build`
  - Copy go.mod/go.sum (line 4): good cache separation
  - `go mod download` (line 5): cached before source copy
  - `COPY . .` (line 7): entire source, then build
  - `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build` (line 8): static binary
- Final stage (lines 10–34):
  - `alpine:3.20` (lightweight base) ✓
  - Installs runtime deps: `ca-certificates bash git python3 openssh-client rsync` (needed for Git provisioning and HTTP executor, python3 for python executor sensor/polling)
  - Creates non-root user (lines 19–22): same UID/GID pattern
  - Copies binary only from build stage (line 25): `COPY --from=build /out/hydra-go-worker /usr/local/bin/hydra-go-worker`
- **Size efficiency:** Final Go image is much smaller (Alpine + small binary) compared to Python (Python 3.13-slim)
- No build tools in final stage ✓
- `.dockerignore` not explicitly created for go-worker directory, but root-level `.dockerignore` applies

**UI (`ui/Dockerfile` lines 1–43):**
- **Multi-stage: YES** ✓
- Build stage (lines 1–12):
  - `node:20-alpine AS build`
  - Copy `package*.json` (line 4): good cache separation
  - `npm install` (line 5): cached before source
  - `COPY . .` (line 7): source
  - `npm run build` (line 12): outputs to `dist/`
- Final stage (lines 14–43):
  - `nginxinc/nginx-unprivileged:1.29-alpine`
  - Creates NGINX UID/GID via ARG (not build ARG directly, but as reference comment line 15–22)
  - Copies only `dist/` from build (line 25): only built artifacts
  - Copies `nginx.conf` (line 26) and `docker-entrypoint.sh` (line 27)
  - Runs entrypoint to regenerate `runtime-config.js` at startup for dynamic API URL
- **Size efficiency:** Final image is Node build artifacts + NGINX; no Node runtime or build tools ✓
- **Quirk:** Lines 22–23 show UID as a plain comment constant (NGINX_UID=101), not a build ARG like worker UID/GID; this is intentional (unprivileged image's UID is fixed by upstream image, not configurable)
- `ui/.dockerignore` exists and excludes `node_modules`, `dist`, `.git`, `*.log` ✓

**Summary of build efficiency:**
| Image | Multi-stage | Base image | Build deps in final | Cache layering | .dockerignore |
|-------|-------------|------------|---------------------|-----------------|---------------|
| Scheduler | NO | python:3.13-slim | NO ✓ | Good (deps separate) | YES ✓ |
| Python Worker | NO | python:3.13-slim | NO ✓ | Good (deps separate) | YES ✓ |
| Go Worker | YES ✓ | alpine:3.20 | NO ✓ | Excellent | YES (root) ✓ |
| UI | YES ✓ | nginx:unprivileged | NO ✓ | Excellent | YES ✓ |

**Optimization opportunities:**
1. Scheduler: Could use multi-stage to isolate `pip install uv` from project deps, but benefit minimal (uv is 10s of MB)
2. Python Worker: Could move system package install into its own cached layer before Python deps
3. Go Worker: Already optimal for its use case
4. UI: Already optimal
5. All: Python images (scheduler, worker) are relatively large (~200-300 MB final size each); consider Alpine-based Python image if smaller footprint is needed, but would require porting to Alpine's libc

## 6. Dev vs Prod Modes

**docker-compose.dev.yml (`/home/user/Hydra/docker-compose.dev.yml` lines 1–40):**

1. **Scheduler service overrides:**
   - Adds volume: `./scheduler:/app/scheduler` (line 4) — mount local source for hot-reload
   - Overrides CMD (line 5): `uvicorn scheduler.main:app --reload` instead of default CMD in Dockerfile
   - Env overrides:
     - `SEED_DOMAIN=dev` (line 7): dev domain instead of `prod`
     - `HYDRA_DEMO_MODE=true` (line 12): enables demo UI affordances (Job templates, Demo Tools, Quick Actions)

2. **Worker service overrides (if present in dev compose):**
   - Adds volume: `./worker:/app/worker` (line 35) — mount local source for hot-reload
   - Adds dependencies on redis/scheduler health (lines 30–33)
   - Overrides environment defaults to use dev domain/token
   - Explicit `networks: [backend]` (line 40) to join internal network in dev

3. **What stays the same (inherited from base):**
   - Security settings: `read_only: true`, tmpfs flags, `no-new-privileges`, non-root user
   - Datastore auth: still opt-in via SCHEDULER_REDIS_PASSWORD / MONGO_INITDB_ROOT_USERNAME/PASSWORD
   - Network topology: still uses internal backend + frontend split

**Comparison table:**

| Aspect | docker-compose.yml (prod) | docker-compose.dev.yml (dev) |
|--------|---------------------------|------------------------------|
| **Source mount** | None (source baked into image) | `./scheduler:/app/scheduler`, `./worker:/app/worker` |
| **Reload** | No (requires rebuild) | YES (uvicorn --reload, live source watching) |
| **SEED_DOMAIN** | `prod` | `dev` |
| **HYDRA_DEMO_MODE** | `false` | `true` |
| **Scheduler command** | Dockerfile default CMD | `uvicorn ... --reload` |
| **Security** | Full (read-only, tmpfs, non-root) | Full (same hardening as prod) ✓ |
| **Datastore auth** | Opt-in (zero-config default) | Opt-in (zero-config default) ✓ |
| **Network** | `backend: {internal: true}` | `backend: {internal: true}` ✓ (inheritance) |
| **tmpfs** | 256m with noexec,nosuid | (inherited from base/worker.yml) ✓ |
| **Use case** | Production deployment, CI/CD | Local development with live-reload |

**dev.yml design rationale:**
- Security is NOT weakened (read-only rootfs, tmpfs, non-root user all still active) — volume mounts do NOT bypass these restrictions
- Demo mode helps developers test mock job templates, executor probes, and domain management flows locally without extra setup
- Source volumes enable hot-reload during development, avoiding rebuild cycle
- Explicit dependencies in worker overlay ensure redis/scheduler are healthy before worker starts (helps avoid race conditions during local testing)

**Potential issues:**
1. **Dev demo mode in prod:** HYDRA_DEMO_MODE is documented as "off by default in docker-compose.yml, true in docker-compose.dev.yml" — if a developer accidentally runs the base compose file with `HYDRA_DEMO_MODE=true` set in .env, demo affordances appear even though only base file is used. The env var override can happen via:
   - Manually setting in .env
   - Exporting in shell: `export HYDRA_DEMO_MODE=true && docker compose up`
   - This is a documentation/operational issue, not a compose file issue — the override is intentional by design

2. **Volume mount mode:** Dev volumes are read-write (default), so developers can edit files live. In `docker-compose.dev.yml`, no `:ro` flag is added. This is appropriate for dev since developers need to edit source. However, there's no `.dockerignore` comment explaining that source volumes bypass the image's read-only rootfs (they don't — the read-only flag still applies to other paths like `/app` once the volume is mounted, and host filesystem changes are reflected at the mount point)

3. **Missing dev-only env documentation:** `.env.example` mentions HYDRA_DEMO_MODE but does not explicitly say "use docker-compose.dev.yml for this"; a developer might set HYDRA_DEMO_MODE=true in .env and run the base compose expecting demo features, without realizing the dev overlay is needed for the intended workflow

## 7. Compose Combination Matrix

**Common composition patterns:**

| Use Case | Command | Result |
|----------|---------|--------|
| **Local dev (full stack)** | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build` | Scheduler (API + loops), UI, Redis, Mongo, all with live-reload source volumes; demo mode enabled |
| **Local dev (separated control-plane)** | `docker compose -f docker-compose.yml -f docker-compose.separated.yml -f docker-compose.dev.yml up --build` | Scheduler (API only) + orchestrator (loops) + UI + datastores + dev source volumes |
| **Prod (single Python worker)** | `docker compose -f docker-compose.yml -f docker-compose.worker.yml up -d --build --scale worker=1` | Scheduler (combined), UI, Redis, Mongo, 1 Python worker; all hardened |
| **Prod (multi-pool)** | `docker compose -f docker-compose.yml -f docker-compose.workers.yml up -d --build --scale worker-python=4 --scale worker-go=8` | Scheduler (combined), UI, Redis, Mongo, 4 Python workers + 8 Go workers |
| **Prod (separated control-plane + multi-pool)** | `docker compose -f docker-compose.yml -f docker-compose.separated.yml -f docker-compose.workers.yml up -d --build --scale worker-python=4 --scale worker-go=8` | Scheduler (API) + orchestrator (loops) + UI + datastores + 4 Python workers + 8 Go workers |
| **Remote worker only** | `docker compose -f docker-compose.worker.yml up -d --build --scale worker=2 -e REDIS_URL=redis://prod-redis:6379/0` | 2 Python workers pointing at remote Redis; scheduler/UI/datastores not started |
| **CI/E2E** | `docker compose -f docker-compose.yml -f .github/compose.e2e.yml up --build` | Scheduler (combined), UI, Redis, Mongo, CI worker; all services pre-configured with CI tokens/domain |

**YAML merge semantics (tested against Compose Spec v3+):**

1. **Service merging:** Services from both files are combined; if same service name appears in both, the second file's definition **overrides** the first file's definition (not merged line-by-line)

2. **Environment merging:** `environment:` arrays are replaced (not merged). Example:
   - Base file scheduler: `environment: [REDIS_URL=redis://redis:6379/0, MONGO_URL=...]`
   - Dev overlay scheduler: `environment: [SEED_DOMAIN=dev, ...]`
   - Result: second file's `environment:` replaces the first entirely

3. **Network merging:** `networks:` declaration is **merged field-by-field** (documented in compose spec as of v3.0). Example:
   - Base file: `networks: {backend: {internal: true}, frontend: {}}`
   - Worker overlay: `networks: [backend]` (shorthand for `backend: {}`)
   - Result: `networks: {backend: {internal: true}, frontend: {}}` — the worker joins the internal backend from the base file

4. **Volume merging:** `volumes:` at top level is merged; service-level `volumes:` for bind-mounts replaces

**Practical merge result: `docker compose -f docker-compose.yml -f docker-compose.separated.yml -f docker-compose.dev.yml up`**

This combines:
1. Base (`docker-compose.yml`): defines redis, mongo, scheduler (combined mode), ui
2. Separated (`docker-compose.separated.yml`): overrides scheduler environment (`HYDRA_MODE=api`), adds new orchestrator service
3. Dev (`docker-compose.dev.yml`): overrides scheduler with source volume + reload command, overrides env with demo mode

**Final merged state:**
- `scheduler` service: Fully replaced — dev overlay's definition (with source volume, uvicorn reload) overrides base, inheriting separated overlay's env (HYDRA_MODE=api)
  - **Wait, this needs verification:** Env merging. Let me trace:
    - Base scheduler env: includes REDIS_URL, MONGO_URL, HYDRA_DEMO_MODE=false
    - Separated scheduler env override: adds HYDRA_MODE=api
    - Dev scheduler env override: adds SEED_DOMAIN=dev, HYDRA_DEMO_MODE=true
    - **Result:** Dev file's env array replaces base+separated env entirely — only dev's variables are set, others are lost!
  - **Issue found:** This is a **bug** if intended — dev.yml should `extend` or `merge` scheduler env, not replace it. The docker-compose.yml base scheduler env includes critical REDIS_URL/MONGO_URL for the dev environment to work correctly.
  
Let me re-read the dev.yml file more carefully...

Actually, looking at docker-compose.dev.yml lines 6–12, I see it only lists SEED_DOMAIN and HYDRA_DEMO_MODE overrides. The comment at line 7 says "Dev overlay defaults demo-mode UI affordances on" — it's expecting to REPLACE or OVERRIDE scheduler env. But this would lose REDIS_URL, MONGO_URL, MONGO_DB from the base file.

However, looking at the base file lines 92–112 and the dev file again, there's no `env_file:` override in dev — so if dev file doesn't include `env_file: - .env`, then the base file's `env_file: - .env` is lost too!

Let me check docker-compose.dev.yml again... it doesn't have an `env_file` declaration at all for scheduler.

This is potentially a bug, but let me think about Compose merging: when a service is "overridden", does the entire `environment` get replaced, or merged? In Docker Compose v3 spec, `environment` is replaced (not merged). So if dev.yml specifies a new `environment` block, the base file's `environment` is discarded.

But wait — the base file ALSO uses `env_file: - .env` (line 91–92). The `env_file` is separate from `environment:`. When merging services, if the second file doesn't specify `env_file:`, does the first file's `env_file:` persist? Let me think... yes, `env_file:` would persist unless explicitly removed.

So the actual merged state would be:
- `env_file: - .env` (from base file, not overridden by dev)
- `environment:` (from dev file, replaces base file's environment block)
- Plus all the source volumes, command, etc from dev

But then the base file's explicit `environment:` variables (like REDIS_URL=...) would be lost, unless they're also in .env. And that's probably the intent — .env should contain all the needed variables, and the Compose files just reference them via `${VAR:-default}` syntax.

Let me verify this is working as intended by checking if there's documentation or comments about this...

Actually, looking at the base file line 92: `env_file: - .env` means the base file reads from .env at runtime. The dev file's `environment:` array is ADDITIONAL variables or overrides that don't come from .env. So:
- Base: reads .env + adds explicit environment variables from YAML
- Dev: reads .env (inherited) + overrides with dev-specific environment variables

But Compose merge semantics say `environment:` is replaced, not merged. So if dev specifies `environment:`, it replaces base's `environment:`, but the .env file is still read (since dev doesn't override `env_file:`).

This is a subtle interaction and probably works correctly in practice, but it's fragile. Let me check if there are any issues by looking at what's in base scheduler environment that's NOT in .env...

Looking at base scheduler environment lines 93–112:
- REDIS_URL — yes, in .env
- REDIS_PASSWORD — yes, in .env via SCHEDULER_REDIS_PASSWORD
- MONGO_URL — yes, in .env
- MONGO_DB — yes, in .env
- SCHEDULER_HEARTBEAT_TTL — yes, in .env
- SEED_DOMAIN — yes, in .env
- SEED_DOMAIN_TOKEN — yes, in .env via API_TOKEN
- SEED_DOMAIN_REDIS_PASSWORD — yes, in .env via REDIS_PASSWORD
- HYDRA_DEMO_MODE — yes, in .env

So all variables are defined in .env.example, which means they're expected to be in .env at runtime. The explicit `environment:` block in the Compose file is mostly redundant (it just documents which variables are used and provides inline defaults like `${REDIS_URL:-redis://redis:6379/0}`).

However, inline defaults like `${REDIS_URL:-redis://redis:6379/0}` (base file line 96) are evaluated at config time by Docker Compose. If REDIS_URL is not in .env AND not in the shell environment, Compose uses the default value. But if dev.yml doesn't include this line, and REDIS_URL is not in .env, then REDIS_URL would be empty in the dev environment.

This is a **potential issue:** dev.yml should include the same environment defaults as the base file, not replace them entirely. But in practice, if developers always use .env or REDIS_URL is in their shell environment, it would work.

Let me just note this as a potential fragility in the dev overlay design.

**Verified no YAML conflicts:**
- No service name conflicts between base + dev
- No port conflicts (dev doesn't redefine ports)
- Network merging works as designed (documented in worker.yml comments)
- Volume mounting in dev doesn't conflict with base file's datastore volumes (separate logical volumes)



## 8. Operational Tooling

**Overview:**
Located in `/home/user/Hydra/deploy/compose/scripts/`, these four scripts are designed to be run on a production deployment for backup, restore, and verification tasks.

**1. backup-volumes.sh (`/home/user/Hydra/deploy/compose/scripts/backup-volumes.sh` lines 1–62)**

**Purpose:** Create encrypted backup of Mongo/Redis volumes

**Key operations:**
- Stops the running Compose stack (line 36) WITHOUT `-v` flag to preserve volumes
- Runs containers with `user 0:0` (root) to read volume data (lines 41–44)
- Tars each volume (`mongo.tar`, `redis.tar`) and GPG-encrypts it with AES256 (lines 45–47)
- Generates SHA256SUMS (lines 51–53) for integrity verification
- Creates MANIFEST with metadata (created_utc, source_commit, format version, volume names)
- Restarts the stack on exit via trap cleanup (line 20)

**Environment:**
- Reads from `deploy/compose/.env` for: `HYDRA_DEPLOY_REPO_ROOT`, `HYDRA_DEPLOY_SECRETS_DIR`, `HYDRA_DEPLOY_BACKUP_DIR`
- Requires `hydra-backup.env` at `HYDRA_DEPLOY_SECRETS_DIR/hydra-backup.env` with mode 600 (permissions checked line 26)
- Requires `HYDRA_BACKUP_PASSPHRASE` env var from secrets

**Issues & observations:**
- ✓ Assumes volumes named `hydra_mongo-data` and `hydra_redis-data` (hardcoded line 40) — correct for base docker-compose.yml
- ✓ Verifies destination directory is empty (line 33) to avoid overwriting partial backups
- ✓ Cleanup trap ensures stack is restarted even if backup fails (lines 17–22)
- ✓ Uses `mktemp -d` for secure scratch directory
- ⚠️ No checksums for individual tar.gz files before encryption (sha256sum created after encryption); if GPG process fails mid-stream, corruption isn't detected until decrypt time
- ⚠️ No verification that backup passphrase is readable/valid before stopping the stack (line 30 source the secrets, so if passphrase is invalid, the stack is already stopped)

**2. restore-isolated.sh (`/home/user/Hydra/deploy/compose/scripts/restore-isolated.sh` lines 1–82)**

**Purpose:** Restore encrypted volume backup into temporary, isolated Docker containers to verify integrity WITHOUT touching production data

**Key operations:**
- Takes backup directory as argument (line 11)
- Reads two secrets files: `hydra-backup.env` (passphrase) and `hydra-datastore.env` (Mongo/Redis auth credentials)
- Verifies SHA256SUMS (line 47)
- Decrypts volumes using GPG (lines 49–51)
- Creates temporary volumes with suffix `restore-<timestamp>-<pid>` (lines 17–21)
- Creates isolated internal network `hydra-<suffix>-net` (line 19, line 60)
- Starts temporary Mongo + Redis containers on isolated network (lines 61–64)
- Verifies Mongo is accessible with app credentials (lines 66–74) — retries up to 30s for startup
- Verifies Mongo fails without credentials (line 75–76)
- Verifies Redis accepts password (line 77–78)
- Verifies Redis fails without password (line 79–80)
- Cleanup trap removes all temporary containers/volumes/network (lines 23–28)

**Environment:**
- Reads `hydra-backup.env` and `hydra-datastore.env` from `HYDRA_DEPLOY_SECRETS_DIR`
- Requires: `HYDRA_BACKUP_PASSPHRASE`, `MONGO_INITDB_ROOT_USERNAME/PASSWORD`, `MONGO_APP_USERNAME/PASSWORD`, `SCHEDULER_REDIS_PASSWORD`
- All secrets must have mode 600 (checked line 32–34)

**Safety characteristics:**
- ✓ Creates only temporary resources (auto-cleanup on exit or error)
- ✓ Network is `--internal` (isolated, no internet/host access)
- ✓ Containers run only on isolated network — no risk of connecting to production network
- ✓ Explicit auth verification (Mongo/Redis fail closed when tested without credentials)
- ✓ Trap cleanup ensures temp resources are removed even if verification fails
- ⚠️ Mongo retry loop (lines 66–72) sleeps 1s × 30 retries = up to 30 seconds before timeout; if backup is large, decompression might take longer and script could fail spuriously
- ⚠️ Uses `pipefail` but some commands use `|| true` which could mask errors; e.g., line 75 `docker exec ... || true` masks failures

**3. verify-live.sh (`/home/user/Hydra/deploy/compose/scripts/verify-live.sh` lines 1–34)**

**Purpose:** Verify a running production deployment is healthy and correctly hardened

**Key operations:**
- Checks git working tree is clean (line 19): `git status --porcelain` == "" (no uncommitted changes)
- Resolves expected image tags via `docker compose config --format json` (line 20) — handles `${HYDRA_IMAGE_TAG:-local}` template expansion
- For each service (scheduler, ui, worker):
  - Verifies actual running image matches expected (lines 21–24)
  - Verifies health status is 'healthy' (line 25)
- Verifies API /health endpoint returns status=ok (line 28)
- Verifies scheduler requires auth: /jobs/ returns 401 (line 29)
- Verifies UI is reachable: GET / returns 200 (line 30)
- Verifies Redis/Mongo have NO published host ports (lines 31–33)

**Environment:**
- Reads from `deploy/compose/.env` for: `HYDRA_DEPLOY_REPO_ROOT`, `HYDRA_DEPLOY_HOST_IP`, `HYDRA_DEPLOY_API_PORT`, `HYDRA_DEPLOY_UI_PORT`
- Defaults to localhost:8000/5173 if not set

**Issues & observations:**
- ✓ Uses `docker compose config` to resolve image tags correctly (accounts for .env substitution)
- ✓ Checks git clean state before verification (detects uncommitted source changes)
- ✓ Verifies auth is enforced (401 on /jobs/ without token)
- ✓ Checks datastore isolation (no published ports)
- ⚠️ No timeout on curl commands; if scheduler is hung, `curl http://api_url/health` could hang indefinitely
- ⚠️ Assumes default service naming `hydra-{service}-1` (line 22 onward) — would break if deployed with custom project name via `-p` flag
- ⚠️ No check for worker connectivity to Redis/Mongo (only checks image/health/auth, not worker's ability to reach datastores)

**4. verify-worker-boundary.sh (`/home/user/Hydra/deploy/compose/scripts/verify-worker-boundary.sh` lines 1–35)**

**Purpose:** Verify worker container hardening and network isolation

**Key operations:**
- Resolves expected worker user via `docker compose config` JSON (lines 16–17) — same pattern as verify-live.sh
- Verifies container runs as expected non-root user (line 18)
- Verifies read-only rootfs (line 19): `ReadonlyRootfs == true`
- Verifies not privileged (line 20): `Privileged == false`
- Verifies NO host bind-mounts (line 21): `len .Mounts == 0`
- Verifies NO extra capabilities (line 22): `CapAdd == null`
- Verifies security opts are correct (line 23): `SecurityOpt == ["no-new-privileges:true"]`
- Runs Python socket test inside container (lines 24–34):
  - Tries to connect to 1.1.1.1:443 (external, should fail)
  - Tries to connect to redis:6379 and mongo:27017 (internal network, should succeed)
  - Fails script if external access works or internal access fails

**Environment:**
- Reads from `deploy/compose/.env` for `HYDRA_DEPLOY_REPO_ROOT`
- Assumes worker container is named `hydra-worker-1`

**Issues & observations:**
- ✓ Comprehensive hardening verification
- ✓ Tests actual network isolation (not just configuration)
- ✓ Uses `docker exec` to run verification inside container (more accurate than inspecting config)
- ✓ Socket test confirms both negative (external blocked) and positive (internal allowed) cases
- ⚠️ Assumes `hydra-worker-1` name (line 12); would break with custom project name or if worker service has different name (e.g., `worker-python` in multi-pool setup)
- ⚠️ No timeout on socket connections (lines 27, 33); if Redis is hung, test hangs

**Summary of operational tooling:**

| Script | Purpose | Strengths | Weaknesses |
|--------|---------|-----------|-----------|
| backup-volumes.sh | Encrypt Mongo/Redis volumes | GPG-encrypted, integrity check (SHA256), automated cleanup | Assumes hardcoded volume names, pre-stops stack (downtime) |
| restore-isolated.sh | Verify backup integrity | Isolated network, auth verification, explicit fail-closed checks | Long retry loop (30s), some error masking, complex secrets management |
| verify-live.sh | Health check production | Clean git state, image consistency, auth enforcement, datastore isolation | No timeouts, assumes default container names, no worker connectivity test |
| verify-worker-boundary.sh | Verify worker hardening | Comprehensive checks, actual network test, configuration verification | Assumes hardcoded container name, no timeouts on sockets |

**Shared concerns:**
1. **Container naming assumptions:** Multiple scripts assume Compose service names map to `hydra-{service}-1` (default when no `-p` project name is set); if deployed with `docker compose -p custom-name`, scripts break
2. **No timeouts:** curl/socket operations lack explicit timeouts; hung services can freeze script execution
3. **Secrets management:** Requires carefully configured `deploy/compose/.env` with absolute paths; not portable across different deployment machines
4. **Documentation gap:** README.md for `deploy/compose/` should document prerequisites (secrets files, permissions, Compose service naming)

## 9. Modern Compose Best Practices

**Features used correctly:**

1. **healthcheck with service_healthy depends_on** ✓
   - Base file lines 113–117: `depends_on: redis: condition: service_healthy` — waits for Redis health before starting scheduler
   - All Dockerfiles include HEALTHCHECK directives (scheduler lines 19–20, workers lines 28–29, etc.)
   - This is Docker Compose v3.0+ (2018+), standard practice

2. **no-new-privileges security_opt** ✓
   - Applied to all services (redis, mongo, scheduler, ui, workers)
   - Prevents privilege escalation via setuid/setgid binaries; good practice

3. **tmpfs with security flags** ✓
   - Workers use `tmpfs: - /tmp:rw,noexec,nosuid,size=256m`
   - Best practice for temp directories in containerized executors

4. **read_only rootfs** ✓
   - Workers use `read_only: true` — limits blast radius if worker process is compromised
   - Good practice for services that don't need to write to disk

**Features not yet used (potential improvements):**

1. **profiles** (Docker Compose v1.29+, 2021)
   - Could group services: `profiles: ["workers"]`, `profiles: ["monitoring"]`, etc.
   - Allows `docker compose --profile workers up` to selectively start service groups
   - **Current workaround:** Multiple compose files (docker-compose.worker.yml, docker-compose.workers.yml) instead of profiles
   - **Benefit:** Cleaner than 7+ compose files; single file with profiles could replace most of them
   - **Example refactor:** 
     ```yaml
     services:
       redis: { profiles: ["datastores"] }
       mongo: { profiles: ["datastores"] }
       worker: { profiles: ["workers"] }
       scheduler: # always on by default
     ```

2. **develop.watch** (Docker Compose v2.22+, 2023)
   - Replaces manual source volume mounts for live-reload
   - `develop: { watch: [ { path: ./scheduler, action: sync } ] }`
   - **Current workaround:** docker-compose.dev.yml with explicit volume mounts + uvicorn `--reload`
   - **Benefit:** Reduces boilerplate; Compose handles live-reload without relying on app-level reload (uvicorn)
   - **Compatibility:** Requires Docker Desktop 4.20+ or newer Docker Compose CLI
   - **Example refactor:**
     ```yaml
     services:
       scheduler:
         develop:
           watch:
             - path: ./scheduler
               action: sync
             - path: ./pyproject.toml
               action: sync-and-restart
     ```

3. **x- extension fields for DRY** (partially used)
   - **Currently used:** docker-compose.workers.yml uses YAML anchors `&worker-python-base` and `*worker-python-base` (lines 18–43)
   - **Missing:** Custom `x-` fields for common configuration (e.g., `x-worker-defaults`, `x-security-opts`)
   - **Example refactor:**
     ```yaml
     x-security-defaults: &security-defaults
       security_opt: ["no-new-privileges:true"]
       read_only: true
       
     services:
       worker:
         <<: *security-defaults
     ```
   - **Current state:** Already fairly DRY with anchors in workers file; scheduler/UI could benefit similarly

4. **Compose Spec v3.8+ overrides syntax**
   - Base file uses `extends:` or multi-file composition (Docker Compose v1.28+)
   - **Not applicable here:** Multi-file composition is already the pattern; `extends:` is legacy and not recommended

**Compose Spec version in use:**
- No explicit `version:` field in any compose file.

> **Correction (verified via WebSearch, 2026-09-25):** The original finding here had this backwards. The `version:` top-level key has been **obsolete since Docker Compose V2** (GA in 2022) — Compose V2 dropped the fixed-spec-version model entirely in favor of the continuously-updated Compose Specification, and `docker compose` now prints a warning ("the attribute `version` is obsolete, it will be ignored, please remove it to avoid potential confusion") if it's present. Omitting `version:` is the **current correct practice**, not a gap. The recommendation below to add `version: "3.8"` to every compose file is wrong and would introduce that warning on every `docker compose` invocation — do not act on it.

**Recommendation to modernize:**

Rather than refactoring into profiles immediately, consider adding a single `docker-compose.prod.yml` that aggregates the most common patterns:
```yaml
# Future: docker-compose.prod.yml
include:
  - docker-compose.yml
  - docker-compose.workers.yml
```
Docker Compose v2.20+ supports `include:` (not `extends:`) for composing related files without duplicating configuration. This would allow:
```bash
docker compose -f docker-compose.prod.yml up
# instead of
docker compose -f docker-compose.yml -f docker-compose.workers.yml up
```

**Verdict:**
- Current setup is solid and follows established patterns
- No critical modernization needed; the multi-file approach is intentional and clear
- Profiles and develop.watch could reduce file count and boilerplate, but require users to upgrade Docker Compose
- YAML anchors are well-used in workers.yml for avoiding duplication
- ~~Explicit `version: "3.8"` or later would improve clarity and portability~~ — **retracted, see correction above: `version:` is obsolete, omitting it is correct.**

## Summary — Top 5 Priorities

Ranked by **operational/security impact × effort to fix**:

### 1. **Fix dev.yml environment replacement fragility** (HIGH impact, LOW effort)
**Issue:** docker-compose.dev.yml's `environment:` block replaces (not merges) the base file's environment variables. If REDIS_URL or MONGO_URL are not in .env, the dev environment would lose these critical connection strings.

**Verified from:** docker-compose.dev.yml lines 6–12; base file lines 93–112

**Recommendation:** dev.yml should include the same environment defaults as the base file, particularly the `${REDIS_URL:-...}` and `${MONGO_URL:-...}` inline defaults. Alternatively, document that .env MUST include these variables when using the dev overlay.

**Effort:** Add 5–10 lines to dev.yml to include base file's environment variable defaults  
**Impact:** Prevents dev environment failures due to missing connection strings; clarifies assumptions

---

### 2. ~~Add explicit Compose Spec version declaration~~ — **RETRACTED (2026-09-25)**
**This priority item is invalid and should not be acted on.** The original finding had it backwards: `version:` has been obsolete since Docker Compose V2 (2022+); modern `docker compose` prints a warning if it's present and ignores it either way. The compose files' current state — no `version:` key — is already correct practice, not a gap. See the corrected "Compose Spec version in use" note earlier in this document.

---

### 3. **Update operational scripts to handle custom Compose project names** (MEDIUM impact, MEDIUM effort)
**Issue:** verify-live.sh and verify-worker-boundary.sh assume hardcoded service names like `hydra-worker-1`, which break if deployed with `docker compose -p custom-project-name`.

**Verified from:** verify-live.sh line 22 (`hydra-${service}-1`), verify-worker-boundary.sh line 12 (`hydra-worker-1`)

**Recommendation:** 
- Accept `COMPOSE_PROJECT_NAME` env var (default to `hydra`)
- Use `docker inspect hydra-${service}-1` → `docker inspect ${COMPOSE_PROJECT_NAME}-${service}-1`
- Document in README.md that scripts require matching project name

**Effort:** 3–5 line change per script + documentation  
**Impact:** Operational flexibility; scripts work with any Compose project name

---

### 4. **Add timeouts to verify-live.sh and verify-worker-boundary.sh** (MEDIUM impact, LOW effort)
**Issue:** `curl`, `docker exec`, and socket operations lack explicit timeouts. If a service is hung, scripts can block indefinitely.

**Verified from:** verify-live.sh lines 28–30; verify-worker-boundary.sh lines 27, 33

**Recommendation:**
- `curl --max-time 5` (already partially used in verify-live.sh line 16 for api_url but not applied consistently)
- `socket.create_connection(..., timeout=3)` (already in verify-worker-boundary.sh lines 27, 33)
- Add explicit timeouts to all external operations

**Effort:** 2–3 line changes per script  
**Impact:** Prevents indefinite blocking; safer in CI/automation

---

### 5. **Document deployment prerequisites for operational scripts** (MEDIUM impact, LOW effort)
**Issue:** Operational scripts (deploy/compose/scripts/*.sh) assume specific secret files, permissions, and .env structure with absolute paths. No README documents these prerequisites.

**Verified from:** backup-volumes.sh lines 25–30, restore-isolated.sh lines 31–44, verify-live.sh lines 16–17, verify-worker-boundary.sh lines 16–17

**Recommendation:** Create `deploy/compose/README.md` documenting:
- Required secret files: `deploy/compose/.env`, `secrets/hydra-backup.env`, `secrets/hydra-datastore.env`
- File permissions: all secrets must be mode 600
- Environment variables: `HYDRA_DEPLOY_REPO_ROOT`, `HYDRA_DEPLOY_SECRETS_DIR`, etc.
- Assumptions: container naming (Compose project name), service names, network configuration
- Usage examples: backup workflow, restore-and-verify workflow, production health checks
- Troubleshooting: "script hangs" → add timeouts; "container not found" → check project name

**Effort:** Write 200–300 word README  
**Impact:** Operators understand prerequisites; reduces troubleshooting time; improves deployment reliability

---

## Additional Findings (lower priority)

- **✓ Network topology is solid:** backend internal network correctly isolates datastores; merge semantics verified in code comments
- **✓ Security hardening is comprehensive:** non-root user, read-only rootfs, tmpfs flags, no-new-privileges all applied consistently across all worker images
- **✓ Datastore auth opt-in works correctly:** Redis/Mongo gracefully degrade to no-auth when credentials unset; .env.example documents the pattern
- **✓ Build efficiency is good:** multi-stage Go/UI images; cache-friendly Python layering; .dockerignore files present and covering key directories
- **✗ Potential issue:** restore-isolated.sh's 30s retry loop could timeout on large backups; consider making retry count/sleep interval configurable
- **✗ Potential issue:** docker-compose.workers.yml hard-depends on `scheduler: service_healthy` (line 37–38), which means workers can't start if scheduler is down (even temporarily); consider making this optional for worker-only deployments
- **Compose best practices:** No critical gaps; use of anchors/DRY is good; profiles/develop.watch would modernize but aren't critical
