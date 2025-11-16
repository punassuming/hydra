#!/usr/bin/env bash
set -euo pipefail

curl -sS -X POST http://localhost:8000/jobs/ \
  -H "Content-Type: application/json" \
  -d @examples/example_jobs.json | jq .

