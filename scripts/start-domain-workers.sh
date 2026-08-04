#!/usr/bin/env bash
set -euo pipefail

# Agentic helper: rotate domain token + Redis ACL, then start/prepare workers.
#
# Usage:
#   ADMIN_TOKEN=... ./scripts/start-domain-workers.sh dev 2
#   WORKER_FLAVOR=go ADMIN_TOKEN=... ./scripts/start-domain-workers.sh dev 2
#   WORKER_BACKEND=k8s K8S_NAMESPACE=hydra K8S_DEPLOYMENT=hydra-worker \
#     ADMIN_TOKEN=... ./scripts/start-domain-workers.sh dev 3
#   WORKER_BACKEND=bare ADMIN_TOKEN=... ./scripts/start-domain-workers.sh dev

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
DOMAIN="${1:-}"
SCALE="${2:-2}"
WORKER_BACKEND="${WORKER_BACKEND:-docker}" # docker | k8s | bare | print
WORKER_FLAVOR="${WORKER_FLAVOR:-python}"   # python | go — only used by WORKER_BACKEND=docker
K8S_NAMESPACE="${K8S_NAMESPACE:-default}"
K8S_DEPLOYMENT="${K8S_DEPLOYMENT:-hydra-worker}"
K8S_SECRET_PREFIX="${K8S_SECRET_PREFIX:-hydra-worker}"
BARE_START_CMD="${BARE_START_CMD:-}"

env_file="$(mktemp /tmp/hydra-worker-XXXXXX.env)"
chmod 600 "${env_file}"
# Remove the temp credentials file automatically for transient backends.
# For bare mode the file is left in place so the user can source it;
# it will be cleaned up on the next run or manually.
if [[ "${WORKER_BACKEND}" != "bare" ]]; then
  trap 'rm -f "${env_file}"' EXIT
fi

if [[ -z "${ADMIN_TOKEN}" ]]; then
  echo "ADMIN_TOKEN is required"
  echo "Usage: ADMIN_TOKEN=<admin_token> $0 <domain> [scale]"
  exit 1
fi

if [[ -z "${DOMAIN}" ]]; then
  echo "Domain argument is required"
  echo "Usage: ADMIN_TOKEN=<admin_token> $0 <domain> [scale]"
  exit 1
fi

if ! [[ "${SCALE}" =~ ^[0-9]+$ ]] || [[ "${SCALE}" -lt 1 ]]; then
  echo "Scale must be a positive integer"
  exit 1
fi

token_json="$(curl -sS -X POST \
  -H "x-api-key: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  "${API_BASE_URL}/admin/domains/${DOMAIN}/token?domain=admin" \
  -d '{}')"

acl_json="$(curl -sS -X POST \
  -H "x-api-key: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  "${API_BASE_URL}/admin/domains/${DOMAIN}/redis_acl/rotate?domain=admin" \
  -d '{}')"

read -r API_TOKEN REDIS_PASSWORD < <(python3 - <<'PY' "${token_json}" "${acl_json}"
import json, sys
token = (json.loads(sys.argv[1]) or {}).get("token", "")
password = ((json.loads(sys.argv[2]) or {}).get("worker_redis_acl") or {}).get("password", "")
print(token, password)
PY
)

if [[ -z "${API_TOKEN}" || -z "${REDIS_PASSWORD}" ]]; then
  echo "Failed to retrieve token/password"
  echo "token response: ${token_json}"
  echo "acl response: ${acl_json}"
  exit 1
fi

{
  echo "DOMAIN=${DOMAIN}"
  echo "API_TOKEN=${API_TOKEN}"
  echo "REDIS_PASSWORD=${REDIS_PASSWORD}"
} > "${env_file}"

echo "Starting ${SCALE} worker(s) for domain=${DOMAIN}"
case "${WORKER_BACKEND}" in
  docker)
    case "${WORKER_FLAVOR}" in
      python)
        compose_file="docker-compose.worker.yml"
        service_name="worker"
        ;;
      go)
        compose_file="docker-compose.worker.go.yml"
        service_name="go-worker"
        ;;
      *)
        echo "Unsupported WORKER_FLAVOR=${WORKER_FLAVOR}. Use 'python' or 'go'."
        exit 1
        ;;
    esac
    DOMAIN="${DOMAIN}" API_TOKEN="${API_TOKEN}" REDIS_PASSWORD="${REDIS_PASSWORD}" \
      docker compose -f "${compose_file}" up -d --build --force-recreate --scale "${service_name}=${SCALE}"
    ;;
  k8s)
    if ! command -v kubectl >/dev/null 2>&1; then
      echo "kubectl is required for WORKER_BACKEND=k8s"
      exit 1
    fi
    secret_name="${K8S_SECRET_PREFIX}-${DOMAIN}"
    kubectl -n "${K8S_NAMESPACE}" create secret generic "${secret_name}" \
      --from-literal=DOMAIN="${DOMAIN}" \
      --from-literal=API_TOKEN="${API_TOKEN}" \
      --from-literal=REDIS_PASSWORD="${REDIS_PASSWORD}" \
      --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n "${K8S_NAMESPACE}" set env "deployment/${K8S_DEPLOYMENT}" --from="secret/${secret_name}"
    kubectl -n "${K8S_NAMESPACE}" scale "deployment/${K8S_DEPLOYMENT}" --replicas="${SCALE}"
    kubectl -n "${K8S_NAMESPACE}" rollout status "deployment/${K8S_DEPLOYMENT}" --timeout=120s || true
    ;;
  bare)
    echo "Bare-metal credentials ready. Export these in your shell or .env file:"
    echo "  export DOMAIN='${DOMAIN}'"
    echo "  export API_TOKEN='${API_TOKEN}'"
    echo "  export REDIS_PASSWORD='${REDIS_PASSWORD}'"
    if [[ -n "${BARE_START_CMD}" ]]; then
      echo "Running bare-metal command with env:"
      DOMAIN="${DOMAIN}" API_TOKEN="${API_TOKEN}" REDIS_PASSWORD="${REDIS_PASSWORD}" bash -lc "${BARE_START_CMD}"
    else
      echo "Set BARE_START_CMD to run your local supervisor/start command automatically."
    fi
    ;;
  print)
    echo "No deployment command executed (WORKER_BACKEND=print)."
    echo "Use this env in your platform:"
    echo "DOMAIN=${DOMAIN}"
    echo "API_TOKEN=${API_TOKEN}"
    echo "REDIS_PASSWORD=${REDIS_PASSWORD}"
    ;;
  *)
    echo "Unsupported WORKER_BACKEND=${WORKER_BACKEND}. Use docker|k8s|bare|print."
    exit 1
    ;;
esac

echo "Verifying scheduler worker visibility..."
workers_json="$(curl -sS -H "x-api-key: ${ADMIN_TOKEN}" "${API_BASE_URL}/workers/?domain=${DOMAIN}")"
python3 - <<'PY' "${workers_json}"
import json, sys
workers = json.loads(sys.argv[1] or "[]")
print(f"online_workers={len(workers)}")
for w in workers:
    print(f"- {w.get('worker_id')} ({w.get('connectivity_status')}/{w.get('dispatch_status')})")
PY

echo "Done."
