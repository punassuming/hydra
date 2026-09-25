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

*Pending investigation...*

## 4. Datastore Auth (opt-in behavior)

*Pending investigation...*

## 5. Build Efficiency & Dockerfiles

*Pending investigation...*

## 6. Dev vs Prod Modes

*Pending investigation...*

## 7. Compose Combination Matrix

*Pending investigation...*

## 8. Operational Tooling

*Pending investigation...*

## 9. Modern Compose Best Practices

*Pending investigation...*

## Summary — Top 5 Priorities

*Pending...*
