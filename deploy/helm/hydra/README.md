# Hydra Helm chart

Deploys the full Hydra stack for a home-lab / small-cluster Kubernetes
environment: Redis, MongoDB, the scheduler (FastAPI control plane), one or
more worker "pools" (Python and/or Go workers, each independently scaled and
placed), and the React UI.

This chart does **not** assume you push images to a registry — the default
workflow is build locally, load the images directly onto your cluster's
nodes, then `helm install`. See [Building and loading images](#building-and-loading-images)
below. The default values reference bare `hydra-*` image names tagged
`0.1.0` — the same version release-please tracks for the whole project
(`pyproject.toml`, `ui/package.json`, this chart's `Chart.yaml`, and these
image tags all move together on release).

## What gets deployed

| Component | Kind | Notes |
|---|---|---|
| Redis | StatefulSet + headless Service | single instance, PVC-backed, no Sentinel/cluster |
| MongoDB | StatefulSet + headless Service | single instance, PVC-backed, no `--replSet` |
| Scheduler | Deployment + Service | `scheduler.mode: separated` splits API and orchestrator into two Deployments |
| UI | Deployment + Service | nginx serving the built React app, runtime-configurable API URL |
| Worker pool(s) | one Deployment (+ optional HPA) per `workers[]` entry | mix Python and Go workers freely |
| Domain seed Secret | Secret | ADMIN_TOKEN, CREDENTIAL_ENCRYPTION_KEY, default-domain token/password — generated once, preserved across upgrades |
| Domain seed Job | Job + RBAC (only if `domainSeed.extraDomains` set) | provisions additional domains beyond the default one |
| Ingress | Ingress ×2 (only if `ingress.enabled`) | one for the UI, one for the scheduler API |

Not included: Postgres or any other job-*target* database — Hydra's own
datastore is Redis + MongoDB only. If you want a Postgres instance to point
`sql` executor jobs at for testing, deploy one separately (it's not part of
Hydra's own stack).

## Prerequisites

- A Kubernetes cluster (k3s, k0s, kind, minikube, or a "real" cluster all work)
- Helm 3
- `kubectl` configured against that cluster
- Docker (or another OCI builder) to build the four images

## Building and loading images

Build all four images from the repo root — tagged to match the version
release-please tracks, so the chart's default `tag: "0.1.0"` values need no
override:

```bash
VERSION=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
docker build -f scheduler/Dockerfile  -t hydra-scheduler:$VERSION  .
docker build -f worker/Dockerfile     -t hydra-worker:$VERSION     .
docker build -f go-worker/Dockerfile  -t hydra-go-worker:$VERSION  go-worker
docker build -f ui/Dockerfile         -t hydra-ui:$VERSION         ui
```

Then load them onto your cluster — the exact command depends on what you're
running:

**k3s** (a very common home-lab choice):
```bash
for img in hydra-scheduler hydra-worker hydra-go-worker hydra-ui; do
  docker save "${img}:${VERSION}" | sudo k3s ctr images import -
done
```

**kind:**
```bash
for img in hydra-scheduler hydra-worker hydra-go-worker hydra-ui; do
  kind load docker-image "${img}:${VERSION}"
done
```

**minikube:**
```bash
for img in hydra-scheduler hydra-worker hydra-go-worker hydra-ui; do
  minikube image load "${img}:${VERSION}"
done
```

**Any containerd node reachable over SSH** (generic fallback):
```bash
docker save "hydra-scheduler:${VERSION}" | ssh <node> sudo ctr -n k8s.io images import -
# repeat per image/node
```

With images loaded, `imagePullPolicy: IfNotPresent` (the chart default) means
Kubernetes uses the locally-loaded image instead of trying to pull from a
registry. If you *do* push to a registry (GHCR, a private registry, etc.),
set `imagePullPolicy: Always` and each component's `image.repository`/`tag`
to your registry path, plus `imagePullSecrets` if it's private.

## Installing

```bash
helm install hydra deploy/helm/hydra -n hydra --create-namespace \
  --set ui.apiBaseUrl=http://localhost:8000   # see IMPORTANT note below
```

After install, run `helm get notes hydra -n hydra` any time to see the
connection/credential instructions again (they're also printed on install).

### `ui.apiBaseUrl` — read this

The UI image is deployable once and pointed at different scheduler endpoints
per environment via a small runtime-config.js the container regenerates from
`HYDRA_API_BASE_URL` at startup — no rebuild needed. But you must set it
explicitly to whatever URL **your browser** can reach:

- Port-forwarding both services: `http://localhost:8000`
- NodePort: `http://<any-node-ip>:<scheduler-nodeport>`
- Ingress enabled: `http://<ingress.scheduler.host value>`

Leaving it empty means the UI falls back to its build-time default
(`http://localhost:8000`), which only works if you're port-forwarding the
scheduler to that exact address.

### Upgrading

```bash
helm upgrade hydra deploy/helm/hydra -n hydra -f my-values.yaml
```

`ADMIN_TOKEN`, `CREDENTIAL_ENCRYPTION_KEY`, and the default domain's
token/Redis password are generated once on install and **preserved** across
upgrades (the chart reads back the existing Secret rather than regenerating
it) — an upgrade never invalidates your worker credentials or encrypted
stored credentials.

### Worker pools

Edit `workers:` in a values file (list `--set` on nested lists is unreliable
in Helm — prefer a values file for anything beyond a single scalar override).
Each entry is an independent Deployment:

```yaml
workers:
  - name: python-default
    flavor: python        # or "go"
    replicas: 3
    domain: prod
    tags: "batch,data"
    maxConcurrency: 4
    image: { repository: hydra-worker, tag: latest }
    resources: { requests: {cpu: 100m, memory: 128Mi}, limits: {cpu: "1", memory: 1Gi} }
    nodeSelector: { "kubernetes.io/hostname": "gpu-node-1" }   # example placement
    autoscaling: { enabled: true, minReplicas: 1, maxReplicas: 10, targetCPUUtilizationPercentage: 70 }
```

- `flavor: python` gets the full feature set (SQL executor, Kerberos/impersonation).
- `flavor: go` is a lighter footprint per pod (no SQL executor, no impersonation)
  — good for scaling many cheap replicas.
- All pools targeting `domainSeed.defaultDomain` (default: `prod`) share the
  auto-seeded credentials automatically — no extra setup.
- A pool targeting a domain **other than** `defaultDomain` needs that domain
  listed in `domainSeed.extraDomains` so the seed Job provisions it (see below).

### Multiple domains

The scheduler seeds exactly one domain automatically on its very first boot.
If every worker pool shares that domain (the default), that's all you need.
If you want workers split across multiple domains, add the extra ones here:

```yaml
domainSeed:
  defaultDomain: prod
  extraDomains: ["ml", "integrations"]
```

This runs a post-install/post-upgrade Job that calls the scheduler's admin
API to create each domain and stores its token + Redis ACL password in a
`<release>-domain-<domain>` Secret, which pools targeting that domain read
from automatically. It's idempotent — already-provisioned domains are
skipped on subsequent upgrades, never re-rotated.

### Persistence / storage class

`redis.persistence.storageClassName` and `mongodb.persistence.storageClassName`
default to empty, which uses your cluster's default StorageClass. Common
home-lab provisioners: k3s ships `local-path` by default; if you run
Longhorn, NFS-subdir-external-provisioner, or something else, set the class
name explicitly. Check what's available with:

```bash
kubectl get storageclass
```

### Control-plane separation (advanced)

`scheduler.mode: separated` splits the API (`scheduler.replicas` pods,
`HYDRA_MODE=api`, no background loops) from the orchestrator (a separate
`orchestrator.replicas`-sized Deployment running the scheduling/failover/SLA
loops). Useful if you want to restart or scale the API independently of the
control plane. Default is `combined` (one Deployment does both) — simplest,
and what most home-lab setups want.

### Demo mode

Off by default. Set `demoMode.enabled: true` to unlock demo/test UI
elements — an executor smoke test and a `depends_on` dependency-graph demo
(Home's "Demo Tools" button), plus a "Create Demo Domain" and credential
round-trip check (Admin's "Demo Quick Actions" card):

```yaml
demoMode:
  enabled: true
```

This is a UI-declutter switch, not an authorization boundary — every action
those elements trigger goes through the same endpoints (`POST /jobs/`,
`POST /admin/domains`, ...) that already work identically either way, so
turning it on doesn't grant any capability a valid token didn't already
have. Leave it off for a production release.

### Ingress

Off by default (assumes nothing beyond ClusterIP Services). Turn on if you
run an ingress controller (nginx-ingress, Traefik, etc.):

```yaml
ingress:
  enabled: true
  className: nginx
  ui:
    host: hydra.home.lab
  scheduler:
    host: hydra-api.home.lab
```

## Uninstalling

```bash
helm uninstall hydra -n hydra
```

Helm does **not** delete the Redis/MongoDB PersistentVolumeClaims (this is
intentional — StatefulSet PVCs survive by default so an accidental
`helm uninstall` doesn't destroy your job history). To actually wipe data:

```bash
kubectl delete pvc -n hydra -l app.kubernetes.io/instance=hydra
```
