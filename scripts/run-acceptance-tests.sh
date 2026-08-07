#!/usr/bin/env bash
set -euo pipefail

# Home-lab acceptance test runner — thin wrapper around
# `pytest tests/acceptance` that sets HYDRA_ACCEPTANCE=1 and surfaces
# missing required config with a clear message instead of a wall of skips.
#
# This script does NOT start or stop your main stack — point it at an
# already-running deployment. See tests/acceptance/README.md for the full
# environment variable reference and worked examples.
#
# Usage:
#   ADMIN_TOKEN=<token> ACCEPTANCE_DOCKER_NETWORK=<network> \
#     ./scripts/run-acceptance-tests.sh
#
#   # Against a live Kubernetes/Helm deployment:
#   ADMIN_TOKEN=<token> ACCEPTANCE_BACKEND=kubectl \
#     ACCEPTANCE_API_URL=http://localhost:8000 \
#     ACCEPTANCE_K8S_NAMESPACE=hydra ACCEPTANCE_K8S_DOMAINS=prod \
#     ./scripts/run-acceptance-tests.sh
#
#   # Pure connectivity/executor smoke check, no chaos/isolation coverage:
#   ADMIN_TOKEN=<token> ACCEPTANCE_BACKEND=none \
#     ACCEPTANCE_EXISTING_DOMAIN=prod ACCEPTANCE_EXISTING_TOKEN=<domain_token> \
#     ./scripts/run-acceptance-tests.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

export HYDRA_ACCEPTANCE=1
export ACCEPTANCE_API_URL="${ACCEPTANCE_API_URL:-http://localhost:8000}"
export ACCEPTANCE_ADMIN_TOKEN="${ACCEPTANCE_ADMIN_TOKEN:-${ADMIN_TOKEN:-}}"
export ACCEPTANCE_BACKEND="${ACCEPTANCE_BACKEND:-docker}"

if [[ -z "${ACCEPTANCE_ADMIN_TOKEN}" ]]; then
  echo "ADMIN_TOKEN (or ACCEPTANCE_ADMIN_TOKEN) is required." >&2
  exit 1
fi

if [[ "${ACCEPTANCE_BACKEND}" == "docker" && -z "${ACCEPTANCE_DOCKER_NETWORK:-}" ]]; then
  echo "ACCEPTANCE_DOCKER_NETWORK is required for the docker backend." >&2
  echo "Find it with: docker inspect <your-redis-container> --format '{{json .NetworkSettings.Networks}}'" >&2
  exit 1
fi

echo "==> Acceptance suite: backend=${ACCEPTANCE_BACKEND} api_url=${ACCEPTANCE_API_URL}"
uv run --frozen pytest tests/acceptance -v "$@"
