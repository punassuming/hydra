#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTEST_BIN="${ROOT}/.venv/bin/pytest"

if [[ -x "$PYTEST_BIN" ]]; then
  PYTEST_CMD=("$PYTEST_BIN")
else
  echo "warning: .venv/bin/pytest not found; falling back to system pytest" >&2
  PYTEST_CMD=("pytest")
fi

cd "$ROOT"
exec "${PYTEST_CMD[@]}" "$@" tests
