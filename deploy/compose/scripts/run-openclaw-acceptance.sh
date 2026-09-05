#!/usr/bin/env bash
# Execute the disposable two-domain Hydra acceptance proof with protected env.
set -euo pipefail

# Pick up HARNESS_* overrides from deploy/compose/.env (see .env.example)
# without requiring every script to duplicate a parsing step.
set -a
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a

repo="${HARNESS_REPO_ROOT:-/srv/openclaw/hydra}"
env_file="${HARNESS_SECRETS_DIR:-/srv/openclaw/secrets}/hydra-scheduler.env"
test -r "$env_file"
test "$(stat -c %a "$env_file")" = 600
set -a
. "$env_file"
set +a
exec env HYDRA_API_URL="${HYDRA_API_URL:-http://${HARNESS_HOST_IP:-127.0.0.1}:${HARNESS_API_PORT:-8000}}" \
  "$repo/.venv/bin/python" "$repo/integrations/openclaw/live_acceptance.py"
