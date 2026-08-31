# Harness pilot cutover runbook

Validated source: branch `deploy`; record the reviewed commit immediately before cutover.

## Preflight

Run from the repository root. This working directory is important because the
Compose build contexts are relative to `deploy/compose/harness`.

```bash
cd /srv/openclaw/hydra
git switch deploy
git status --short                 # must be empty
git rev-parse HEAD                 # expected reviewed commit
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml config -q
docker volume inspect hydra-pilot-redis-data hydra-pilot-mongo-data
stat -c '%n %a %U:%G' /srv/openclaw/secrets/hydra-scheduler.env /srv/openclaw/secrets/hydra-worker.env /srv/openclaw/secrets/hydra-datastore.env
```

Build application images with the commit-specific local tags. Keep the
known-good recovery image under its separate tag; never retag it as part of a
failed build.

```bash
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml build --pull=false
```

## Cutover

The expected interruption is a brief service recreation. Redis and Mongo remain
attached to the existing named volumes. After *every* secret or Compose change,
the following full recreation is mandatory so each process takes the current
authenticated connection configuration. Do not use `down -v`, change ports, or
migrate OpenClaw cron.

```bash
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml up -d --build --force-recreate
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml ps
```

Verify the Docker health checks, authenticated Redis and Mongo probes (using
the protected files without printing them), authenticated worker registration
for `hydra-harness-pilot-01`, and only `10.10.40.40:8000` and
`10.10.40.40:5173` as Hydra host listeners. Redis/Mongo must have no host
published ports. The worker/datastore backend network is internal-only; a
worker must not be able to create a direct outbound TCP connection. Scheduler
and UI additionally join the frontend network so their explicit LAN listener
mappings continue to work. If changing either network property, use
`docker compose -p hydra down` (never `down -v`) before the mandatory
recreation so Docker can replace the network without touching named volumes.

## Datastore authentication migration

Create `/srv/openclaw/secrets/hydra-datastore.env` mode `0600`, owned by the
service operator. It contains distinct random values for `REDIS_CONTROL_PASSWORD`,
`MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`,
`MONGO_APP_USERNAME`, and `MONGO_APP_PASSWORD`, plus the derived authenticated
`MONGO_URL` and scheduler `REDIS_PASSWORD`; it is never committed or shown in
logs.

For an existing unauthenticated Mongo volume, create the Mongo root user and
the `hydra` application user with `readWrite` on `hydra_jobs` *before* enabling
`--auth`, then run the mandatory full recreation above. This is an in-place,
non-destructive migration. If user creation cannot be verified before enabling
auth, stop: do not reset or delete the named volumes. A reset/reseed requires
an explicit separately approved command: stop the stack, take a verified backup,
remove only `hydra-pilot-mongo-data` and `hydra-pilot-redis-data`, recreate the
stack, and reseed the protected domain credentials.

### Redacted in-place migration record — 2026-08-31

- Generated `/srv/openclaw/secrets/hydra-datastore.env` mode `0600`; no secret
  values were committed or printed.
- Created `hydra_root` with `root@admin` and `hydra` with
  `readWrite@hydra_jobs` before enabling Mongo `--auth`.
- Set a distinct Redis default-user control-plane password and verified that
  unauthenticated `PING` is rejected while credentialed `PING` returns `PONG`.
- Ran the mandatory `docker compose -p hydra ... up -d --build --force-recreate`.
  The existing `hydra-pilot-redis-data` and `hydra-pilot-mongo-data` volumes
  were retained.
- Post-cutover: Mongo unauthenticated access was rejected; the `hydra` user
  authenticated to `hydra_jobs`; Redis control-plane authentication succeeded;
  scheduler, worker, UI, Redis, and Mongo all reported healthy. No workload was
  submitted.

## Encrypted backup and isolated restore

Use the scripts below. They read protected host secret files, never write
secrets or backup contents into the checkout, and never use `down -v`.

```bash
install -d -m 700 /srv/openclaw/backups/hydra
deploy/compose/harness/scripts/backup-volumes.sh /srv/openclaw/backups/hydra/DATE
deploy/compose/harness/scripts/restore-isolated.sh /srv/openclaw/backups/hydra/DATE
```

The backup script briefly stops the project for a consistent raw-volume archive,
encrypts Mongo and Redis separately, and starts the existing stack. The restore
script uses only disposable volumes and an internal-only temporary network,
validates positive and negative datastore authentication, then removes its
temporary containers, network, volumes, and plaintext work area.

### Redacted backup/restore record — 2026-08-31

- Created encrypted Mongo and Redis archives with a SHA-256 manifest under the
  protected backup root; no plaintext archive or credential was retained there.
- Restored both archives into disposable internal-only state. Mongo app and
  Redis control authentication passed; unauthenticated Mongo/Redis access was
  rejected.
- Temporary restore resources were removed automatically. Canonical named
  volumes were not reset or deleted.

## Rollback

If build or startup fails, preserve the failed images and logs, then restore the
known-good deploy revision in the canonical checkout without deleting volumes:

```bash
cd /srv/openclaw/hydra
git switch --detach 2789f54
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml up -d --build --force-recreate
```

Use an approved revision that retains the current backend/frontend network
topology.  For a rollback across a network-topology change, run `docker
compose -p hydra -f deploy/compose/harness/docker-compose.yml down` first
(never `down -v`), then recreate from the target revision.  This preserves the
named datastore volumes while allowing Docker to replace incompatible networks.

The harness definition must reference known-good application images, including
the separately retained `hydra-pilot-worker:recovery` image where required.
Confirm the same endpoints/listeners, healthy containers, unchanged secret
file metadata, and unchanged named volumes. Record the failure before retrying.

### Redacted rollback execution record — 2026-08-31

- Checked out an auth-compatible approved commit in detached mode and performed
  the forced Compose recreation.
- Scheduler health reported `workers=1`; Redis/Mongo authenticated probes
  passed; neither datastore had a host-published port.
- Returned to canonical `deploy` and recreated the stack. No volume was
  deleted. The target shares application artifact `deploy-53aef84` because
  later commits in this sequence are deployment configuration/evidence.

## Worker boundary verification

The worker is non-root (`10001:10001`), read-only, non-privileged, has no
Docker socket or host mount, no added Linux capabilities, and uses
`no-new-privileges`. Its backend network is internal-only with scheduler,
Mongo, and Redis; only scheduler/UI join the frontend network for LAN ingress.

### Redacted boundary record — 2026-08-31

- A pre-policy direct worker TCP connection to `1.1.1.1:443` succeeded.
- After the backend/frontend split, the same bounded connection was denied
  while scheduler health (`workers=1`) and LAN UI/API checks passed.
- Redis and Mongo remain backend-only with no host-published ports.
