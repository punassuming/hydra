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
published ports.

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

## Rollback

If build or startup fails, preserve the failed images and logs, then restore the
known-good deploy revision in the canonical checkout without deleting volumes:

```bash
cd /srv/openclaw/hydra
git switch --detach 81bce90795b8e77ae7e5a828bd568484831a3aa6
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml up -d --build
```

The harness definition must reference known-good application images, including
the separately retained `hydra-pilot-worker:recovery` image where required.
Confirm the same endpoints/listeners, healthy containers, unchanged secret
file metadata, and unchanged named volumes. Record the failure before retrying.
