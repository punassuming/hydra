#!/usr/bin/env bash
set -euo pipefail

# Run a worker pointing at an existing scheduler/redis/mongo stack.
if [ "$#" -eq 0 ]; then
  docker compose -f docker-compose.worker.yml up --build
else
  docker compose -f docker-compose.worker.yml up "$@"
fi
