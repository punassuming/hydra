---
name: hydra-domain-triage
description: Troubleshoot Hydra domain administration and worker visibility issues by checking scheduler auth/domain state and optionally verifying Redis token-hash linkage across Docker, Kubernetes, or direct redis-cli backends.
---

# Hydra Domain Triage

Use this skill when the user cannot login to a domain, workers do not appear online, or token/ACL behavior seems inconsistent.

## Primary workflow

1. Ensure `ADMIN_TOKEN` is available.
2. Run:
```bash
ADMIN_TOKEN=<admin_token> ./scripts/diagnose-domain-admin.sh <domain>
```
3. Choose Redis deep-check mode via `REDIS_CHECK_MODE`:
- `auto` (default): detects docker/k8s/cli
- `docker`: inspect Redis via container exec
- `k8s`: inspect Redis via kubectl exec
- `cli`: inspect via `redis-cli -u REDIS_URL`
- `none`: API-only diagnostics

## What this validates

- Scheduler health and auth path
- Domain presence in admin domain list
- Scheduler worker visibility for domain
- Redis token hash (`token_hash:<domain>`) vs worker `domain_token_hash`

## Backend-specific inputs

- Docker:
  - `DOCKER_REDIS_CONTAINER`
- Kubernetes:
  - `K8S_NAMESPACE`
  - `K8S_REDIS_POD` (optional; auto-discovers via the Helm chart's `app.kubernetes.io/component=redis` label, falling back to the legacy `app=redis` label)
- Redis CLI:
  - `REDIS_URL`
  - `REDIS_PASSWORD` (optional if embedded/auth not required)

## Output expectations

Report findings in severity order:
1. auth/domain mismatch
2. worker registration mismatch
3. deployment/backend connectivity issues

Then provide the exact corrective command(s).

## Guardrails

- Keep domain/user terminology consistent:
  - `DOMAIN` identifies domain and Redis ACL username scope.
  - `API_TOKEN` authenticates scheduler API requests.
  - `REDIS_PASSWORD` authenticates Redis worker access.
- Do not suggest combining API token and Redis password.
