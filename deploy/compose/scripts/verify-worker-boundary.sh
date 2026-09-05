#!/usr/bin/env bash
# Verify worker hardening and that only private backend dependencies work.
set -euo pipefail

worker=hydra-worker-1
test "$(docker inspect "$worker" --format '{{.Config.User}}')" = '10001:10001'
test "$(docker inspect "$worker" --format '{{.HostConfig.ReadonlyRootfs}}')" = true
test "$(docker inspect "$worker" --format '{{.HostConfig.Privileged}}')" = false
test "$(docker inspect "$worker" --format '{{len .Mounts}}')" = 0
test "$(docker inspect "$worker" --format '{{json .HostConfig.CapAdd}}')" = null
test "$(docker inspect "$worker" --format '{{json .HostConfig.SecurityOpt}}')" = '["no-new-privileges:true"]'
docker exec "$worker" python - <<'PY'
import socket
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3)
except OSError:
    pass
else:
    raise SystemExit("worker external TCP unexpectedly allowed")
for host, port in (("redis", 6379), ("mongo", 27017)):
    socket.create_connection((host, port), timeout=3).close()
PY
echo 'worker_boundary=passed'
