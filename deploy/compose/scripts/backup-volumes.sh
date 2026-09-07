#!/usr/bin/env bash
# Create a consistent encrypted backup of the canonical Hydra Mongo/Redis volumes.
set -euo pipefail

# Pick up HYDRA_DEPLOY_* overrides from deploy/compose/.env (see .env.example)
# without requiring every script to duplicate a parsing step.
set -a
[ -f "$(dirname "$0")/../.env" ] && . "$(dirname "$0")/../.env"
set +a

repo="${HYDRA_DEPLOY_REPO_ROOT:-/opt/hydra}"
secrets="${HYDRA_DEPLOY_SECRETS_DIR:-/opt/hydra/secrets}/hydra-backup.env"
destination=${1:-${HYDRA_DEPLOY_BACKUP_DIR:-/opt/hydra/backups}/$(date -u +%Y%m%dT%H%M%SZ)}
scratch=$(mktemp -d)
was_stopped=0

cleanup() {
  rm -rf "$scratch"
  if [ "$was_stopped" = 1 ]; then
    (cd "$repo" && docker compose -p hydra up -d --no-build) || true
  fi
}
trap cleanup EXIT

test -r "$secrets"
test "$(stat -c %a "$secrets")" = 600
set -a
. "$secrets"
set +a
: "${HYDRA_BACKUP_PASSPHRASE:?missing protected backup passphrase}"

install -d -m 700 "$destination"
test -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)"

# Raw Mongo files are copied only while quiesced; never use down -v here.
(cd "$repo" && docker compose -p hydra stop)
was_stopped=1

for datastore in mongo redis; do
  volume="hydra_${datastore}-data"
  docker run --rm --user 0:0 \
    -v "${volume}:/source:ro" \
    -v "${scratch}:/backup" \
    redis:7-alpine sh -ec "cd /source && tar -cf /backup/${datastore}.tar . && chmod 0644 /backup/${datastore}.tar"
  gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
    --symmetric --cipher-algo AES256 \
    --output "${destination}/${datastore}.tar.gpg" "${scratch}/${datastore}.tar" 3<<<"$HYDRA_BACKUP_PASSPHRASE"
done

(
  cd "$destination"
  sha256sum mongo.tar.gpg redis.tar.gpg > SHA256SUMS
)
{
  printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_commit=%s\n' "$(git -C "$repo" rev-parse HEAD)"
  printf 'format=encrypted-raw-volume-v1\n'
  printf 'mongo_volume=hydra_mongo-data\nredis_volume=hydra_redis-data\n'
} > "${destination}/MANIFEST"

echo "backup_dir=${destination}"
