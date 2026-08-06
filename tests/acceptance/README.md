# Home-lab acceptance suite

A pytest suite that stands up (or points at) a real Hydra deployment and
verifies the whole system actually works — not just that each service
imports cleanly, but that domains are isolated, every executor type
succeeds, mixed worker pools route correctly, and the deployment recovers
from the failures a home lab is likely to hit (a worker dying mid-job,
Redis or Mongo restarting).

It's deliberately separate from `tests/` proper: those are fast, mocked,
run-on-every-commit unit tests. This suite talks to a live scheduler over
HTTP, takes minutes rather than seconds, and needs real infrastructure —
so it's opt-in (skips entirely unless `HYDRA_ACCEPTANCE=1`) and never runs
in CI.

## Quick start

```bash
# Docker Compose home lab, fully automated (spins up throwaway domains +
# worker containers on your existing network, tears them down after):
ADMIN_TOKEN=<your admin token> \
ACCEPTANCE_DOCKER_NETWORK=<network your redis/scheduler containers are on> \
./scripts/run-acceptance-tests.sh

# Already-installed Kubernetes/Helm deployment (verifies what's there;
# does not create or scale anything Helm doesn't already manage):
ADMIN_TOKEN=<your admin token> ACCEPTANCE_BACKEND=kubectl \
ACCEPTANCE_API_URL=http://localhost:8000 \
ACCEPTANCE_K8S_NAMESPACE=hydra ACCEPTANCE_K8S_DOMAINS=prod \
./scripts/run-acceptance-tests.sh

# Just prove a domain + worker you already have running actually works
# (no chaos, no isolation coverage, no provisioning):
ADMIN_TOKEN=<your admin token> ACCEPTANCE_BACKEND=none \
ACCEPTANCE_EXISTING_DOMAIN=prod ACCEPTANCE_EXISTING_TOKEN=<domain token> \
./scripts/run-acceptance-tests.sh
```

Or run pytest directly (the script above is just a thin wrapper that sets
`HYDRA_ACCEPTANCE=1` and checks the required vars are present):

```bash
HYDRA_ACCEPTANCE=1 ACCEPTANCE_ADMIN_TOKEN=<token> ACCEPTANCE_BACKEND=docker \
ACCEPTANCE_DOCKER_NETWORK=<network> \
uv run pytest tests/acceptance -v
```

## The three backends — what each one actually does

| | `docker` | `kubectl` | `none` |
|---|---|---|---|
| Provisions domains | Yes, throwaway, torn down after | No — uses `ACCEPTANCE_K8S_DOMAINS`, domains you already created via the Helm chart | No — uses `ACCEPTANCE_EXISTING_DOMAIN` |
| Provisions workers | Yes, throwaway containers via `docker run` | No — uses whatever pools the Helm chart already installed | No |
| Executor matrix | Yes | Yes | Yes |
| Domain isolation | Yes (dynamically created domains) | Only if you also set `ACCEPTANCE_K8S_DOMAIN_TOKENS` | No |
| Mixed worker-pool routing (Python vs Go) | Yes | No (pool topology is Helm's job, not this suite's) | No |
| Worker-kill failover | Yes | No | No |
| Redis/Mongo restart self-heal | Yes, if you set the container name(s) | Redis only, if you set `ACCEPTANCE_K8S_REDIS_STATEFULSET` | No |

**Why kubectl mode doesn't dynamically provision anything:** the Helm
chart's `workers:` list is the source of truth for what pools exist and
which domains they serve, fixed at `helm install`/`upgrade` time. A test
suite reaching in to create ad-hoc Deployments alongside that would fight
the chart rather than verify it. So `kubectl` mode is "point it at what you
already installed and prove it works," not "spin up new infrastructure."
`docker` mode is the one that does full dynamic provisioning — reach for it
even for a Kubernetes-bound home lab if you want the fuller coverage
(worker-pool routing, failover, isolation) validated before you `helm
install` for real.

## Environment variables

### Core

| Variable | Default | Notes |
|---|---|---|
| `HYDRA_ACCEPTANCE` | unset | Master gate — the entire suite skips unless this is `1` |
| `ACCEPTANCE_API_URL` | `http://localhost:8000` | Scheduler URL as seen from wherever you run pytest |
| `ACCEPTANCE_INTERNAL_API_URL` | backend-dependent (see below) | Scheduler URL as seen from a *worker* — only matters for the `http`/`sensor` executor checks |
| `ACCEPTANCE_ADMIN_TOKEN` | **required** | Your `ADMIN_TOKEN` |
| `ACCEPTANCE_BACKEND` | `none` | `docker` \| `kubectl` \| `none` |
| `ACCEPTANCE_TIMEOUT_SECONDS` | `90` | Default per-job wait timeout |
| `ACCEPTANCE_KEEP` | `0` | Set `1` to skip teardown of anything this run created (useful for debugging a failure) |

`ACCEPTANCE_INTERNAL_API_URL` defaults to `http://scheduler:8000` for the
docker backend (matching `docker-compose.yml`'s service name),
`http://<release>-scheduler.<namespace>.svc.cluster.local:8000` for
kubectl, and `ACCEPTANCE_API_URL` itself for `none`. Override it if your
topology doesn't match those defaults.

### Docker backend (`ACCEPTANCE_BACKEND=docker`)

| Variable | Default | Notes |
|---|---|---|
| `ACCEPTANCE_DOCKER_NETWORK` | **required** | Network your main stack's containers are on. Find it: `docker inspect <redis-container> --format '{{json .NetworkSettings.Networks}}'` |
| `ACCEPTANCE_DOCKER_REDIS_URL` | `redis://redis:6379/0` | How a throwaway worker container reaches Redis |
| `ACCEPTANCE_DOCKER_MAX_CONCURRENCY` | `2` | Per throwaway worker |
| `ACCEPTANCE_DOCKER_REDIS_CONTAINER` | unset | Enables the Redis-restart self-heal test — the actual container name (`docker ps`) |
| `ACCEPTANCE_DOCKER_MONGO_CONTAINER` | unset | Enables the Mongo-restart resilience test |

### Kubectl backend (`ACCEPTANCE_BACKEND=kubectl`)

| Variable | Default | Notes |
|---|---|---|
| `ACCEPTANCE_K8S_NAMESPACE` | `hydra` | |
| `ACCEPTANCE_K8S_RELEASE` | `hydra` | Your `helm install <release> deploy/helm/hydra` release name |
| `ACCEPTANCE_K8S_DOMAINS` | unset (**required**) | Comma-separated domains already installed via the chart, e.g. `prod,ml` |
| `ACCEPTANCE_K8S_DOMAIN_TOKENS` | unset | Comma-separated, same order as above — enables the real isolation check. Without these, checks use the admin token + a domain override, which proves execution works but not token-scoped isolation |
| `ACCEPTANCE_K8S_REDIS_STATEFULSET` | unset | Enables the Redis-restart self-heal test — the chart names it `<release>-hydra-redis` unless you've overridden `fullnameOverride` |

### `none` backend / bring-your-own-domain smoke mode

| Variable | Notes |
|---|---|
| `ACCEPTANCE_EXISTING_DOMAIN` | A domain that already has a worker running |
| `ACCEPTANCE_EXISTING_TOKEN` | Its domain token |

### Optional executor coverage

| Variable | Notes |
|---|---|
| `ACCEPTANCE_SQL_CONNECTION_URI` | Set to run the `sql` executor test against a real database. Unset = skipped |
| `ACCEPTANCE_SQL_DIALECT` | `postgres` (default) \| `mysql` \| `mssql` \| `oracle` \| `mongodb` |
| `ACCEPTANCE_TEST_EXTERNAL` | Set `1` to run the `external` executor test |
| `ACCEPTANCE_EXTERNAL_BINARY` | `/bin/echo` (default) — must exist on the worker host/image |
| `ACCEPTANCE_EXTERNAL_ARGS` | `hydra-acceptance-ok` (default), comma-separated |

The `shell`, `python`, `http`, and `sensor` executors are always exercised
(the latter two poll the scheduler's own `/health` endpoint, so they need
no external dependency).

## What this does NOT cover — check these manually

Per-run assertions can't cover everything worth checking before you trust a
home-lab deployment. Before going further:

- **`CREDENTIAL_ENCRYPTION_KEY` set explicitly**, not derived from
  `ADMIN_TOKEN`. Not observable via the API by design (would be an
  information leak) — check the scheduler's startup logs for the
  `CREDENTIAL_ENCRYPTION_KEY is not set` warning, or grep your env config.
  If it's not set, rotating `ADMIN_TOKEN` later will silently make every
  stored credential unreadable.
- **Backups.** MongoDB is the source of truth for job definitions, run
  history, domains, and encrypted credentials. Confirm something backs up
  the `mongo-data` volume/PVC before relying on this for anything real —
  this suite doesn't (and shouldn't) touch backup/restore.
- **TLS/ingress**, if you're exposing the scheduler or UI outside your home
  network — not exercised here.
- **True Mongo HA** (replica sets, automatic failover) — the resilience
  tests restart a single Mongo instance and confirm the scheduler
  reconnects; they don't stand up or fail over a replica set.
- **Non-default executors you don't plan to use.** The matrix covers every
  executor type Hydra supports, but Kerberos/impersonation aren't in it
  (they need a real KDC/OS user setup that's inherently host-specific) —
  test those by hand against your actual target hosts if you use them.

## Design notes

- All chaos/provisioning code lives in `_infra.py`, isolated from the HTTP
  test logic in `_jobs.py`/`_client.py` — if your setup needs a different
  way to restart a container or launch a worker, that's the one file to
  change.
- Domain/credential provisioning goes through the same admin API endpoints
  `scripts/start-domain-workers.sh` uses (`POST /admin/domains`,
  `.../redis_acl/rotate`) rather than shelling out to that script and
  scraping its output — same effect, more reliable to assert against.
- Every domain/worker this suite creates is cleaned up at the end unless
  `ACCEPTANCE_KEEP=1`. If a run is interrupted before cleanup, docker-backend
  containers are labeled `hydra-acceptance=1` — remove stragglers with
  `docker ps -aq --filter label=hydra-acceptance=1 | xargs -r docker rm -f`.
