#!/usr/bin/env bash
set -euo pipefail

# Run a worker pointing at an existing scheduler/redis/mongo stack.
#
# Usage:
#   ./scripts/worker-up.sh                       # Python worker (default)
#   WORKER_FLAVOR=go ./scripts/worker-up.sh       # Go worker
#   ./scripts/worker-up.sh -d --scale worker=3    # extra args pass through
#
# For multiple different worker pools running together (mixed Python/Go,
# different tags/domains), see docker-compose.workers.yml instead.

WORKER_FLAVOR="${WORKER_FLAVOR:-python}"

case "${WORKER_FLAVOR}" in
  python)
    compose_file="docker-compose.worker.yml"
    ;;
  go)
    compose_file="docker-compose.worker.go.yml"
    ;;
  *)
    echo "Unsupported WORKER_FLAVOR=${WORKER_FLAVOR}. Use 'python' or 'go'."
    exit 1
    ;;
esac

if [ "$#" -eq 0 ]; then
  docker compose -f "${compose_file}" up --build
else
  docker compose -f "${compose_file}" up "$@"
fi
