#!/usr/bin/env bash
# Verify the running deployment without printing credentials.
set -euo pipefail

# Pick up HYDRA_DEPLOY_* overrides from deploy/compose/.env (see .env.example)
# without requiring every script to duplicate a parsing step.
set -a
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a

repo="${HYDRA_DEPLOY_REPO_ROOT:-/opt/hydra}"
# scheduler/ui are defined in the standard docker-compose.yml; a worker
# deployed alongside it comes from docker-compose.worker.yml (or one of its
# variants). Resolve via `compose config` (not a raw grep of the YAML) since
# image tags are templated (${HYDRA_IMAGE_TAG:-local}), not literal strings.
api_url=${HYDRA_API_URL:-http://${HYDRA_DEPLOY_HOST_IP:-127.0.0.1}:${HYDRA_DEPLOY_API_PORT:-8000}}
ui_url=${HYDRA_UI_URL:-http://${HYDRA_DEPLOY_HOST_IP:-127.0.0.1}:${HYDRA_DEPLOY_UI_PORT:-5173}}

test "$(git -C "$repo" status --porcelain)" = ""
resolved=$(cd "$repo" && docker compose -f docker-compose.yml -f docker-compose.worker.yml config --format json)
for service in scheduler ui worker; do
  expected=$(printf '%s' "$resolved" | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['$service']['image'])")
  actual=$(docker inspect "hydra-${service}-1" --format '{{.Config.Image}}')
  test "$actual" = "$expected"
  test "$(docker inspect "hydra-${service}-1" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')" = healthy
done

test "$(curl -fsS --max-time 5 "$api_url/health" | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x["status"], x["workers"])')" = "ok 1"
test "$(curl -sS -o /dev/null -w '%{http_code}' "$api_url/jobs/")" = 401
test "$(curl -sS -o /dev/null -w '%{http_code}' "$ui_url/")" = 200
for store in redis mongo; do
  test -z "$(docker inspect "hydra-${store}-1" --format '{{range $port,$bindings := .NetworkSettings.Ports}}{{if $bindings}}published{{end}}{{end}}')"
done
echo 'live_verification=passed'
