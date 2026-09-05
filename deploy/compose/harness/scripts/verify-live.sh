#!/usr/bin/env bash
# Verify the running Harness deployment without printing credentials.
set -euo pipefail

repo=/srv/openclaw/hydra
compose_file="$repo/deploy/compose/harness/docker-compose.yml"
api_url=${HYDRA_API_URL:-http://10.10.40.40:8000}
ui_url=${HYDRA_UI_URL:-http://10.10.40.40:5173}

test "$(git -C "$repo" status --porcelain)" = ""
for service in scheduler ui worker; do
  expected=$(awk -v service="$service" '
    $0 == "  " service ":" { found=1; next }
    found && $1 == "image:" { print $2; exit }
  ' "$compose_file")
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
