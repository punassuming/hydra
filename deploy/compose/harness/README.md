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

The application images are tagged locally as `harness-scheduler:deploy-b618dda`,
`harness-ui:deploy-b618dda`, and `harness-worker:deploy-b618dda`. Build and
recreate are transactional with respect to the separate known-good recovery
reference; do not retag `hydra-pilot-worker:recovery` during a retry.

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
`hydra-pilot-worker:recovery` image untouched, then restore the prior Compose
definition and run `docker compose -f /srv/openclaw/hydra-pilot/docker-compose.yml
up -d --no-build`. The live cutover runbook records the exact recovery tag and
verification commands.
