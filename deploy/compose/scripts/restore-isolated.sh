#!/usr/bin/env bash
# Restore an encrypted volume backup into disposable, internal-only Docker state.
set -euo pipefail

# Pick up HARNESS_* overrides from deploy/compose/.env (see .env.example)
# without requiring every script to duplicate a parsing step.
set -a
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a

backup_dir=${1:?usage: restore-isolated.sh BACKUP_DIR}
secrets_dir="${HARNESS_SECRETS_DIR:-/srv/openclaw/secrets}"
secrets="$secrets_dir/hydra-backup.env"
datastore_secrets="$secrets_dir/hydra-datastore.env"
scratch=$(mktemp -d)
suffix="restore-$(date -u +%Y%m%d%H%M%S)-$$"
mongo_volume="hydra-${suffix}-mongo"
redis_volume="hydra-${suffix}-redis"
network="hydra-${suffix}-net"
mongo_container="hydra-${suffix}-mongo"
redis_container="hydra-${suffix}-redis"

cleanup() {
  docker rm -f "$mongo_container" "$redis_container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$mongo_volume" "$redis_volume" >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT

test -r "$secrets"
test "$(stat -c %a "$secrets")" = 600
test -r "$datastore_secrets"
test "$(stat -c %a "$datastore_secrets")" = 600
set -a
. "$secrets"
. "$datastore_secrets"
set +a
: "${HYDRA_BACKUP_PASSPHRASE:?missing protected backup passphrase}"
: "${MONGO_INITDB_ROOT_USERNAME:?missing Mongo root username}"
: "${MONGO_INITDB_ROOT_PASSWORD:?missing Mongo root password}"
: "${MONGO_APP_USERNAME:?missing Mongo app username}"
: "${MONGO_APP_PASSWORD:?missing Mongo app password}"
: "${SCHEDULER_REDIS_PASSWORD:?missing Redis control password}"

test -f "$backup_dir/MANIFEST"
(cd "$backup_dir" && sha256sum -c SHA256SUMS >/dev/null)
for datastore in mongo redis; do
  gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
    --decrypt --output "${scratch}/${datastore}.tar" "${backup_dir}/${datastore}.tar.gpg" 3<<<"$HYDRA_BACKUP_PASSPHRASE"
done

docker volume create "$mongo_volume" >/dev/null
docker volume create "$redis_volume" >/dev/null
for datastore in mongo redis; do
  volume_var="${datastore}_volume"
  docker run --rm --user 0:0 -v "${!volume_var}:/target" -v "${scratch}:/backup:ro" redis:7-alpine \
    sh -ec "cd /target && tar -xf /backup/${datastore}.tar"
done
docker network create --internal "$network" >/dev/null
docker run -d --name "$mongo_container" --network "$network" -v "${mongo_volume}:/data/db" mongo:6.0 \
  mongod --auth --bind_ip_all --setParameter diagnosticDataCollectionEnabled=false >/dev/null
docker run -d --name "$redis_container" --network "$network" -e "SCHEDULER_REDIS_PASSWORD=$SCHEDULER_REDIS_PASSWORD" -v "${redis_volume}:/data" redis:7-alpine \
  sh -ec 'exec redis-server --appendonly yes --requirepass "$SCHEDULER_REDIS_PASSWORD"' >/dev/null

for _ in $(seq 1 30); do
  if printf '%s\n%s\n' "$MONGO_APP_USERNAME" "$MONGO_APP_PASSWORD" | docker exec -i "$mongo_container" sh -ec \
    'read -r user; read -r pass; mongo --quiet --username "$user" --password "$pass" --authenticationDatabase hydra_jobs hydra_jobs --eval "db.runCommand({ping:1}).ok"' 2>/dev/null | grep -qx 1; then
    break
  fi
  sleep 1
done
printf '%s\n%s\n' "$MONGO_APP_USERNAME" "$MONGO_APP_PASSWORD" | docker exec -i "$mongo_container" sh -ec \
  'read -r user; read -r pass; mongo --quiet --username "$user" --password "$pass" --authenticationDatabase hydra_jobs hydra_jobs --eval "db.runCommand({ping:1}).ok"' | grep -qx 1
mongo_unauth=$(docker exec "$mongo_container" mongo --quiet --eval 'db.getSiblingDB("hydra_jobs").stats()' 2>&1 || true)
case "$mongo_unauth" in *Unauthorized*|*not\ authorized*) ;; *) echo 'isolated Mongo did not fail closed' >&2; exit 1;; esac
printf '%s\n' "$SCHEDULER_REDIS_PASSWORD" | docker exec -i "$redis_container" sh -ec \
  'read -r pass; REDISCLI_AUTH="$pass" redis-cli --user default ping' | grep -qx PONG
redis_unauth=$(docker exec "$redis_container" redis-cli ping 2>&1 || true)
case "$redis_unauth" in *NOAUTH*) ;; *) echo 'isolated Redis did not fail closed' >&2; exit 1;; esac

echo 'isolated_restore=passed'
