#!/usr/bin/env bash
# Execute the disposable two-domain Hydra acceptance proof with protected env.
set -euo pipefail

repo=/srv/openclaw/hydra
env_file=/srv/openclaw/secrets/hydra-scheduler.env
test -r "$env_file"
test "$(stat -c %a "$env_file")" = 600
set -a
. "$env_file"
set +a
exec env HYDRA_API_URL="${HYDRA_API_URL:-http://10.10.40.40:8000}" \
  "$repo/.venv/bin/python" "$repo/integrations/openclaw/live_acceptance.py"
