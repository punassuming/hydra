# Compose deployment runbook

Durable operator procedures for deploying, verifying, backing up, and rolling
back a Docker Compose deployment of Hydra using the root `docker-compose.yml`
(+ a worker compose file). Commands below use the defaults from
[`README.md`](README.md)'s prerequisites (`HARNESS_REPO_ROOT`,
`HARNESS_SECRETS_DIR`, etc.) — substitute your own via a local `.env` (see
[`.env.example`](.env.example)) if they differ.

## Prerequisites

See [`README.md`](README.md#prerequisites) for the secret files and their
required permissions.

## Preflight checks

Run from the repository root — this matters because Compose build contexts
are relative to it.

```bash
cd "${HARNESS_REPO_ROOT:-/srv/openclaw/hydra}"
git switch main
git status --short                 # must be empty
git rev-parse HEAD                 # record the commit you're about to deploy
docker compose -p hydra -f docker-compose.yml -f docker-compose.worker.yml config -q
docker volume inspect hydra_redis-data hydra_mongo-data
stat -c '%n %a %U:%G' "${HARNESS_SECRETS_DIR:-/srv/openclaw/secrets}"/hydra-{scheduler,worker}.env
```

Build application images:

```bash
docker compose -p hydra -f docker-compose.yml -f docker-compose.worker.yml build --pull=false
```

## Cutover (build + recreate)

The expected interruption is a brief service recreation. Redis and Mongo
remain attached to their existing named volumes. After *any* secret or
Compose change, a full recreation is required so every process picks up the
current configuration. Never use `down -v` for a routine cutover.

```bash
docker compose -p hydra -f docker-compose.yml -f docker-compose.worker.yml up -d --build --force-recreate
docker compose -p hydra -f docker-compose.yml -f docker-compose.worker.yml ps
```

Verify: containers report healthy (`docker compose ... ps`), the worker
registers with the scheduler, and only the scheduler/UI ports you configured
(`SCHEDULER_PORT`/`UI_PORT`, restricted to `BIND_IP` if you set one) are
listening — Redis/Mongo must have no host-published ports at all. If you're
changing the `backend`/`frontend` network topology itself (not just which
services exist), run `docker compose -p hydra down` (never `down -v`) first
so Compose can replace the networks without touching named volumes, then
redo the cutover above.

Run [`scripts/verify-live.sh`](scripts/verify-live.sh) to check all of this
automatically.

## Datastore authentication migration

Hydra's bundled Redis/MongoDB run without auth by default (see the main
README's "Hardening, opt-in" section). To turn auth on for an *existing*,
already-running, unauthenticated deployment without losing data:

1. Create `hydra-datastore.env` (see [`README.md`](README.md#prerequisites))
   with distinct random values for `SCHEDULER_REDIS_PASSWORD`,
   `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, and (if you
   want a Mongo user scoped to just `hydra_jobs` rather than using the root
   user everywhere) `MONGO_APP_USERNAME`/`MONGO_APP_PASSWORD` — plus the
   scheduler's own `MONGO_URL` updated to include credentials. Never commit
   this file or print its contents.
2. **Before** the deployment's Mongo is restarted with auth enabled, connect
   to the running (still-unauthenticated) Mongo and create the root user and,
   if using one, the scoped application user (`readWrite` on `hydra_jobs`).
   If you can't verify these users were created, stop — do not proceed to
   step 3, and do not reset or delete the named volumes.
3. Run the mandatory full recreation from **Cutover** above. This is an
   in-place, non-destructive migration — Mongo/Redis's official images pick
   up `--auth`/`--requirepass` from the env vars themselves (see the comments
   in `docker-compose.yml`).

A full reset/reseed (rather than an in-place migration) is a separate,
deliberate operation: stop the stack, take a verified backup (below), then
remove only the `hydra_mongo-data`/`hydra_redis-data` volumes, recreate the
stack, and reseed domain credentials from scratch.

*Verified working end to end*: root/scoped-user creation before enabling
`--auth`, unauthenticated `PING`/commands rejected post-cutover, credentialed
access succeeding, all services healthy with no workload disruption.

## Encrypted backup and isolated restore

```bash
install -d -m 700 "${HARNESS_BACKUP_DIR:-/srv/openclaw/backups/hydra}"
scripts/backup-volumes.sh "${HARNESS_BACKUP_DIR:-/srv/openclaw/backups/hydra}/$(date -u +%Y%m%dT%H%M%SZ)"
scripts/restore-isolated.sh "${HARNESS_BACKUP_DIR:-/srv/openclaw/backups/hydra}/<the timestamp above>"
```

`backup-volumes.sh` briefly stops the deployment for a consistent raw-volume
archive, encrypts Mongo and Redis separately (GPG symmetric, passphrase from
`hydra-backup.env`), and restarts the stack — it never uses `down -v` and
never writes secrets or plaintext archives into the checkout.
`restore-isolated.sh` decrypts a backup into brand-new, disposable,
internal-only-networked volumes/containers (never touching the live
deployment), confirms both authenticated access succeeds and unauthenticated
access is rejected, then removes its temporary containers, network, volumes,
and plaintext work area automatically.

*Verified working end to end*: encrypted Mongo/Redis archives with a
SHA-256 manifest, restored into disposable isolated state, authenticated
access passing and unauthenticated access rejected on the restored copy, no
temporary resources or plaintext left behind.

## Rollback

If a build or startup fails, preserve the failed images/logs, then restore a
known-good revision without deleting volumes:

```bash
cd "${HARNESS_REPO_ROOT:-/srv/openclaw/hydra}"
git switch --detach <last known-good reviewed commit>
docker compose -p hydra -f docker-compose.yml -f docker-compose.worker.yml up -d --build --force-recreate
```

Pick a revision that shares the current `backend`/`frontend` network
topology. Rolling back across a network-topology change needs `docker
compose -p hydra down` first (never `down -v`) so Compose can replace the
networks, then recreate from the target revision — this preserves the named
datastore volumes while letting Docker replace incompatible networks.
Afterward, confirm the same endpoints/listeners, healthy containers,
unchanged secret file metadata, and unchanged named volumes. Record the
failure (commit, symptoms, what you tried) before retrying — pasting a
specific historical commit here as a "known good" example would go stale the
moment another commit lands, so there is deliberately no fixed SHA above.

*Verified working end to end*: detached checkout of an auth-compatible
revision, forced recreation, scheduler/health/UI checks passing on the rolled
back version, then returning to the canonical revision and recreating again
— all without deleting any named volume.

## Worker boundary verification

The worker container is non-root (a dedicated UID/GID, not 0), read-only
root filesystem, non-privileged, no Docker socket or host mount, no added
Linux capabilities, `no-new-privileges`. Its network (`backend`) is
internal-only, reachable from Redis/Mongo/scheduler but with no path to the
open internet; only the scheduler/UI join `frontend` for their published
ports.

```bash
scripts/verify-worker-boundary.sh
```

*Verified working end to end*: a direct worker-to-internet TCP connection is
denied, while the scheduler stays healthy and Redis/Mongo connectivity from
the worker continues to work.
