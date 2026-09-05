# Harness Compose pilot

This is the version-controlled deployment definition for the private Harness
pilot. It intentionally exposes only the UI and scheduler API on the local
network:

- UI: `http://10.10.40.40:5173/`
- API: `http://10.10.40.40:8000/`

Redis and MongoDB have no host port mappings. Secrets are supplied only from
the protected host files below; never commit their contents or copy them into
the repository.

## Prerequisites

- Docker Engine with Compose v2 on Harness.
- The checkout is the intended deployed revision.
- `/srv/openclaw/secrets/hydra-scheduler.env` and
  `/srv/openclaw/secrets/hydra-worker.env` exist with mode `0600` and are
  readable only by the service operator.

The scheduler environment must contain the Hydra control-plane secrets,
including the admin token. The worker environment must contain only the
domain-scoped worker credentials required by the selected worker domain.

## Deploy

From the repository root on Harness:

```bash
git checkout deploy
git pull --ff-only origin deploy
docker compose -f deploy/compose/harness/docker-compose.yml up -d --build
```

The Compose file records the exact local image tags for the deployed revision.
Build and recreate are transactional with respect to the separate known-good
recovery reference; do not retag `hydra-pilot-worker:recovery` during a retry.

Verify only the intended listeners are present:

```bash
curl --fail http://10.10.40.40:8000/health
curl --fail http://10.10.40.40:5173/
docker compose -f deploy/compose/harness/docker-compose.yml ps
ss -lnt | rg '10.10.40.40:(5173|8000)'
```

The API must reject unauthenticated job requests. Confirm an unauthenticated
`GET /jobs/` returns `401`, then use a domain token to make an authenticated
read. Do not put tokens on a shell command line or in this repository.

## Rollback and data handling

`docker compose stop` stops the pilot without deleting its named Redis or
MongoDB volumes. Do not use `down -v` unless destruction of job history is
explicitly approved. To roll back code, check out the previous known-good
`deploy` commit and run `up -d --build` again. Backup and restore volume data
separately under the host's protected backup policy.

For a failed image build, leave the existing containers and the separate
`hydra-pilot-worker:recovery` image untouched, then restore the prior deploy
revision in the canonical checkout and run the harness definition again:

```bash
cd /srv/openclaw/hydra
git switch --detach 81bce90795b8e77ae7e5a828bd568484831a3aa6
docker compose -p hydra -f deploy/compose/harness/docker-compose.yml up -d --build
```

The live cutover runbook records the exact recovery tag and verification
commands. Never use the retired pilot tree or the root `docker-compose.yml`
for rollback.

## Reusable verification helpers

These commands avoid printing credentials and operate only on the canonical
Harness deployment:

```bash
deploy/compose/harness/scripts/verify-live.sh
deploy/compose/harness/scripts/verify-worker-boundary.sh
deploy/compose/harness/scripts/backup-volumes.sh /srv/openclaw/backups/hydra/DATE
deploy/compose/harness/scripts/restore-isolated.sh /srv/openclaw/backups/hydra/DATE
deploy/compose/harness/scripts/run-openclaw-acceptance.sh
```

The final command creates and deletes disposable domains and harmless jobs. It
is an acceptance operation, not a routine health check.
