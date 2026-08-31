# Harness pilot cutover runbook

Validated source: branch `deploy`, commit `b618dda47f1b0cb0c9e945e577a0fdf784918dc4` plus the reviewed worker identity fix in this commit.

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
docker image inspect harness-scheduler:deploy-b618dda harness-ui:deploy-b618dda harness-worker:deploy-b618dda
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
known-good root Compose definition without deleting volumes:

```bash
docker compose -p hydra-pilot -f /srv/openclaw/hydra-pilot/docker-compose.yml up -d --no-build
```

The root definition must reference a known-good application image, including
the separately retained `hydra-pilot-worker:recovery` image where required.
Confirm the same endpoints/listeners, healthy containers, unchanged secret
file metadata, and unchanged named volumes. Record the failure before retrying.
