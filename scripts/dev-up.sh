#!/usr/bin/env bash
set -euo pipefail

# Bring up the full dev stack with hot reload mounts. Pass extra args to override defaults.
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)
DEFAULT_SERVICES=(redis mongo scheduler worker ui)

if [ "$#" -eq 0 ]; then
  docker compose "${COMPOSE_FILES[@]}" up --build "${DEFAULT_SERVICES[@]}"
else
  docker compose "${COMPOSE_FILES[@]}" up "$@"
fi
