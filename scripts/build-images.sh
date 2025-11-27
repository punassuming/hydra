#!/usr/bin/env bash
set -euo pipefail

# Build images for scheduler, worker, and UI (respects VITE_API_BASE_URL if set).
docker compose build scheduler worker ui
