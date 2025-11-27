#!/usr/bin/env bash
set -euo pipefail

# Stop the dev stack. Set NUKE=1 to drop volumes.
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)

if [ "${NUKE:-0}" -eq 1 ]; then
  docker compose "${COMPOSE_FILES[@]}" down -v
else
  docker compose "${COMPOSE_FILES[@]}" down
fi
