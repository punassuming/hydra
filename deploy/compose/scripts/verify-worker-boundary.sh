#!/usr/bin/env bash
# Verify worker hardening and that only private backend dependencies work.
set -euo pipefail

# Pick up HYDRA_DEPLOY_* overrides from deploy/compose/.env (see .env.example)
# without requiring every script to duplicate a parsing step.
set -a
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a

repo="${HYDRA_DEPLOY_REPO_ROOT:-/opt/hydra}"
worker=hydra-worker-1
# Resolve the expected user via `compose config` (the repo root's own .env,
# not this directory's) rather than re-deriving the HYDRA_WORKER_UID/GID
# default here too — same reasoning as verify-live.sh's image-tag check.
expected_user=$(cd "$repo" && docker compose -f docker-compose.yml -f docker-compose.worker.yml config --format json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['worker']['user'])")
test "$(docker inspect "$worker" --format '{{.Config.User}}')" = "$expected_user"
test "$(docker inspect "$worker" --format '{{.HostConfig.ReadonlyRootfs}}')" = true
test "$(docker inspect "$worker" --format '{{.HostConfig.Privileged}}')" = false
test "$(docker inspect "$worker" --format '{{len .Mounts}}')" = 0
test "$(docker inspect "$worker" --format '{{json .HostConfig.CapAdd}}')" = null
test "$(docker inspect "$worker" --format '{{json .HostConfig.SecurityOpt}}')" = '["no-new-privileges:true"]'
docker exec "$worker" python - <<'PY'
import socket
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3)
except OSError:
    pass
else:
    raise SystemExit("worker external TCP unexpectedly allowed")
for host, port in (("redis", 6379), ("mongo", 27017)):
    socket.create_connection((host, port), timeout=3).close()
PY
echo 'worker_boundary=passed'
