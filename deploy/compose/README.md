# Compose deployment: operational tooling

The standard way to run Hydra via Docker Compose is the root
[`docker-compose.yml`](../../docker-compose.yml) (+ `docker-compose.worker.yml`
or one of its variants for a worker) — see the main
[`README.md`](../../README.md#docker-deployment) for that. This directory
holds operational tooling *beyond* what `docker compose` itself provides:
encrypted backup/restore, post-deploy live verification, and a worker
network-boundary check. It was originally built for one specific always-on
deployment and still defaults to that deployment's values, but every value is
overridable — copy [`.env.example`](.env.example) to `.env` here to point it
at a different host/checkout without editing the scripts.

## Prerequisites

- Docker Engine with Compose v2 on the deployment host.
- A git checkout at `HARNESS_REPO_ROOT` (default `/srv/openclaw/hydra`) that
  is the intended deployed revision.
- Protected secret files under `HARNESS_SECRETS_DIR` (default
  `/srv/openclaw/secrets`), each mode `0600`, readable only by the service
  operator, never committed:
  - `hydra-scheduler.env` — the scheduler's control-plane secrets (admin
    token, etc.), loaded via `docker-compose.yml`'s `env_file: .env` (point
    `.env` at this file, or copy its contents in).
  - `hydra-worker.env` — domain-scoped worker credentials only.
  - `hydra-datastore.env` — only if you've opted into Redis/Mongo auth (see
    the main README's "Hardening, opt-in" section); contains
    `SCHEDULER_REDIS_PASSWORD`, `MONGO_INITDB_ROOT_USERNAME`,
    `MONGO_INITDB_ROOT_PASSWORD`, and (if you maintain a separate scoped
    Mongo application user beyond the root user) `MONGO_APP_USERNAME`/
    `MONGO_APP_PASSWORD`.
  - `hydra-backup.env` — only for `backup-volumes.sh`/`restore-isolated.sh`;
    contains `HYDRA_BACKUP_PASSPHRASE`.

See [`RUNBOOK.md`](RUNBOOK.md) for the deploy/verify/rollback/backup
procedures themselves.

## Scripts

All read their protected secret files directly (mode-600-checked) and never
print credentials. All pick up `HARNESS_*` overrides from a `.env` in this
directory if present (see `.env.example`).

- `scripts/backup-volumes.sh [DEST]` — stops the stack briefly for a
  consistent raw-volume copy, encrypts Mongo and Redis separately (GPG
  symmetric), restarts the stack. Never uses `down -v`.
- `scripts/restore-isolated.sh BACKUP_DIR` — decrypts a backup into brand-new,
  disposable, internal-only-networked containers/volumes (never touches the
  live deployment), asserts both authenticated access works and
  unauthenticated access is rejected, then tears everything down.
- `scripts/verify-live.sh` — checks the live deployment's running images
  match what's currently checked out, containers are healthy, `/health`
  reports the expected worker count, unauthenticated `/jobs/` is rejected,
  the UI responds, and Redis/Mongo have no host-published ports.
- `scripts/verify-worker-boundary.sh` — checks the worker container's
  hardening (non-root UID/GID, read-only rootfs, no added capabilities, no
  mounts, `no-new-privileges`) and that it can reach Redis/Mongo but not the
  open internet.
- `scripts/run-openclaw-acceptance.sh` — runs
  `integrations/external_client/live_acceptance.py`'s disposable two-domain
  acceptance suite (creates and deletes real throwaway domains/jobs) against
  the live deployment. An acceptance operation, not a routine health check.
