#!/usr/bin/env bash
set -euo pipefail

# Run scheduler/worker tests and optional UI build check.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

cd "$ROOT"
echo "==> pytest (scheduler/worker)"
pytest ${PYTEST_ARGS:-} tests/test_scheduler.py tests/test_worker.py

if [ "${E2E:-0}" -eq 1 ]; then
  echo "==> pytest (end-to-end)"
  pytest ${PYTEST_ARGS:-} tests/test_end_to_end.py
else
  echo "==> skipping end-to-end tests (set E2E=1 to enable)"
fi

if [ -d "$ROOT/ui" ]; then
  if [ -d "$ROOT/ui/node_modules" ]; then
    echo "==> npm run build (ui)"
    (cd "$ROOT/ui" && npm run build)
  else
    echo "==> skipping ui build (ui/node_modules missing; run npm install)" >&2
  fi
fi
