#!/usr/bin/env bash
set -euo pipefail

# Agentic helper: diagnose domain admin and worker-registration issues.
#
# Usage:
#   ADMIN_TOKEN=... ./scripts/diagnose-domain-admin.sh dev
# Optional:
#   REDIS_CHECK_MODE=none|auto|docker|k8s|cli
#   DOCKER_REDIS_CONTAINER=hydra-redis-1
#   K8S_NAMESPACE=hydra K8S_REDIS_POD=redis-0
#   REDIS_URL=redis://localhost:6379/0 REDIS_PASSWORD=...

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
DOMAIN="${1:-}"
REDIS_CHECK_MODE="${REDIS_CHECK_MODE:-auto}"
DOCKER_REDIS_CONTAINER="${DOCKER_REDIS_CONTAINER:-hydra-redis-1}"
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"
K8S_REDIS_POD="${K8S_REDIS_POD:-}"
REDIS_URL="${REDIS_URL:-}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

if [[ -z "${ADMIN_TOKEN}" ]]; then
  echo "ADMIN_TOKEN is required"
  echo "Usage: ADMIN_TOKEN=<admin_token> $0 <domain>"
  exit 1
fi

if [[ -z "${DOMAIN}" ]]; then
  echo "Domain argument is required"
  echo "Usage: ADMIN_TOKEN=<admin_token> $0 <domain>"
  exit 1
fi

echo "== Scheduler health =="
curl -sS -H "x-api-key: ${ADMIN_TOKEN}" "${API_BASE_URL}/health?domain=${DOMAIN}" || true
echo
echo

echo "== Domain list entry =="
domains_json="$(curl -sS -H "x-api-key: ${ADMIN_TOKEN}" "${API_BASE_URL}/admin/domains?domain=admin")"
python3 - <<'PY' "${domains_json}" "${DOMAIN}"
import json, sys
domains = (json.loads(sys.argv[1]) or {}).get("domains", [])
target = sys.argv[2]
hit = next((d for d in domains if d.get("domain") == target), None)
print(hit if hit else f"domain {target!r} not found")
PY
echo

echo "== Scheduler worker view =="
workers_json="$(curl -sS -H "x-api-key: ${ADMIN_TOKEN}" "${API_BASE_URL}/workers/?domain=${DOMAIN}")"
python3 - <<'PY' "${workers_json}"
import json, sys
workers = json.loads(sys.argv[1] or "[]")
print(f"workers_visible={len(workers)}")
for w in workers:
    print(f"- {w.get('worker_id')} heartbeat_age={w.get('heartbeat_age_seconds')} status={w.get('connectivity_status')}/{w.get('dispatch_status')}")
PY
echo

redis_mode="${REDIS_CHECK_MODE}"

if [[ "${redis_mode}" == "auto" ]]; then
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -q "^${DOCKER_REDIS_CONTAINER}\$"; then
    redis_mode="docker"
  elif command -v kubectl >/dev/null 2>&1; then
    if [[ -z "${K8S_REDIS_POD}" ]]; then
      # Helm chart (deploy/helm/hydra) labels Redis app.kubernetes.io/component=redis;
      # fall back to the legacy app=redis label for hand-rolled manifests.
      K8S_REDIS_POD="$(kubectl -n "${K8S_NAMESPACE}" get pods -l app.kubernetes.io/component=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
      if [[ -z "${K8S_REDIS_POD}" ]]; then
        K8S_REDIS_POD="$(kubectl -n "${K8S_NAMESPACE}" get pods -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
      fi
    fi
    if [[ -n "${K8S_REDIS_POD}" ]]; then
      redis_mode="k8s"
    fi
  elif command -v redis-cli >/dev/null 2>&1 && [[ -n "${REDIS_URL}" ]]; then
    redis_mode="cli"
  else
    redis_mode="none"
  fi
fi

redis_raw() {
  local cmd=("$@")
  case "${redis_mode}" in
    docker)
      docker exec "${DOCKER_REDIS_CONTAINER}" redis-cli --raw "${cmd[@]}"
      ;;
    k8s)
      kubectl -n "${K8S_NAMESPACE}" exec "${K8S_REDIS_POD}" -- redis-cli --raw "${cmd[@]}"
      ;;
    cli)
      if [[ -n "${REDIS_PASSWORD}" ]]; then
        redis-cli -u "${REDIS_URL}" -a "${REDIS_PASSWORD}" --raw "${cmd[@]}"
      else
        redis-cli -u "${REDIS_URL}" --raw "${cmd[@]}"
      fi
      ;;
    *)
      echo "Unsupported redis_mode=${redis_mode}" >&2
      return 1
      ;;
  esac
}

if [[ "${redis_mode}" == "none" ]]; then
  echo "Skipping Redis deep checks (no supported Redis inspection backend detected)"
  exit 0
fi

echo "== Redis token/worker hash checks (${redis_mode}) =="
expected_hash="$(redis_raw get "token_hash:${DOMAIN}" || true)"
echo "expected_token_hash=${expected_hash}"
echo

echo "worker_keys:"
redis_raw keys "workers:${DOMAIN}:*" || true
echo

mapfile -t worker_keys < <(redis_raw keys "workers:${DOMAIN}:*" | sed '/^$/d' || true)
if [[ "${#worker_keys[@]}" -eq 0 ]]; then
  echo "no worker keys found"
  exit 0
fi

for key in "${worker_keys[@]}"; do
  got="$(redis_raw hget "${key}" domain_token_hash | tr -d '\r' || true)"
  verdict="MISMATCH"
  if [[ -n "${expected_hash}" && "${got}" == "${expected_hash}" ]]; then
    verdict="OK"
  fi
  echo "${key}: ${verdict} hash=${got}"
done
