#!/usr/bin/env bash
set -euo pipefail

# Create a domain and token via the admin API.
# Usage: ADMIN_TOKEN=... [API_BASE=http://localhost:8000] [DISPLAY=...] [DESC=...] [TOKEN=...] ./scripts/create-domain.sh <domain>

if [ -z "${ADMIN_TOKEN:-}" ]; then
  echo "ADMIN_TOKEN is required (admin token for scheduler API)" >&2
  exit 1
fi

DOMAIN=${1:-}
if [ -z "$DOMAIN" ]; then
  echo "Usage: ADMIN_TOKEN=... ./scripts/create-domain.sh <domain>" >&2
  exit 1
fi

API_BASE=${API_BASE:-http://localhost:8000}
DISPLAY=${DISPLAY:-$DOMAIN}
DESC=${DESC:-}
TOKEN=${TOKEN:-}

PAYLOAD=$(python - <<'PY'
import json, os
payload = {
    "domain": os.environ["DOMAIN"],
    "display_name": os.environ["DISPLAY"],
    "description": os.environ["DESC"],
}
token = os.environ.get("TOKEN")
if token:
    payload["token"] = token
print(json.dumps(payload))
PY
)

RESP=$(curl -sSf -X POST "$API_BASE/admin/domains" \
  -H "x-api-key: $ADMIN_TOKEN" \
  -H "content-type: application/json" \
  -d "$PAYLOAD")

echo "$RESP" | python - <<'PY'
import json, sys
data = json.load(sys.stdin)
print("domain:", data.get("domain"))
token = data.get("token")
if token:
    print("token:", token)
else:
    print("token: <not returned>")
PY
