# Harness pilot cutover runbook

Validated source: branch `deploy`, commit `254b4e99ed6d75930b13f2a62121f2e0781961be`.

## Preflight

Run from the repository root. This working directory is important because the
Compose build contexts are relative to `deploy/compose/harness`.

```bash
cd /srv/openclaw/hydra
git switch deploy
git status --short                 # must be empty
git rev-parse HEAD                 # expected reviewed commit
docker compose -p hydra-pilot -f deploy/compose/harness/docker-compose.yml config -q
docker volume inspect hydra-pilot-redis-data hydra-pilot-mongo-data
stat -c '%n %a %U:%G' /srv/openclaw/secrets/hydra-*.env
```

Build application images with the commit-specific local tags. Keep the
known-good recovery image under its separate tag; never retag it as part of a
failed build.

```bash
docker compose -p hydra-pilot -f deploy/compose/harness/docker-compose.yml build --pull=false
docker image inspect harness-scheduler:deploy-254b4e9 harness-ui:deploy-254b4e9 harness-worker:deploy-254b4e9
```

## Cutover

The expected interruption is the brief scheduler/worker recreation required by
Compose; Redis and Mongo remain attached to the existing named volumes. Do not
use `down -v`, change ports, or migrate OpenClaw cron.

```bash
docker compose -p hydra-pilot -f deploy/compose/harness/docker-compose.yml up -d --no-build
docker compose -p hydra-pilot -f deploy/compose/harness/docker-compose.yml ps
```

Verify UI/API 200, unauthenticated `GET /jobs/` 401, authenticated worker
registration for `hydra-harness-pilot-01`, and only `10.10.40.40:8000` and
`10.10.40.40:5173` as Hydra host listeners. Redis/Mongo must have no host
published ports.

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
