#!/bin/sh
set -eu

# Writes a small runtime-config.js from HYDRA_API_BASE_URL before nginx
# starts, so this image can be deployed against different scheduler
# endpoints (different domains/ingress hosts) without a rebuild.
# See ui/src/api/client.ts for how the app consumes window.__HYDRA_API_BASE__.

value="${HYDRA_API_BASE_URL:-}"
# Escape backslashes and double quotes so the value is safe inside a JS string literal.
escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')

cat > /usr/share/nginx/html/runtime-config.js <<EOF
window.__HYDRA_API_BASE__ = "${escaped}";
EOF

exec nginx -g "daemon off;"
