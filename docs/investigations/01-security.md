# Security Investigation: Hydra Jobs
**Date:** 2026-09-25  
**Investigator:** Claude Haiku 4.5  
**Status:** In Progress

---

## Overview
Live security audit of the Hydra Jobs distributed job runner, covering authentication, authorization, credential handling, executors, network isolation, supply-chain risks, and AI features.

---

## 1. AuthN/AuthZ
**Status:** ✓ Reviewed | **Severity:** Low

**Files Reviewed:** `scheduler/utils/auth.py`, `scheduler/api/jobs.py`, `scheduler/api/logs.py`, `scheduler/api/events.py`, `scheduler/api/admin.py`

### GOOD
- **HMAC timing-safe comparison** (`scheduler/utils/auth.py:64`) — Uses `hmac.compare_digest()` for token validation (not vulnerable to timing attacks)
- **Domain token requires both token AND domain** (line 94-95) — Rejects requests without domain parameter when using domain token
- **Domain scoping consistently enforced** — All DB queries in jobs/logs/workers APIs filter by domain for non-admin users
- **SSE/Log streams respect domain** — Both `events.py:24` and `logs.py:34` check domain match before streaming
- **Admin domain override validated** (`admin.py:33-34`) — Validates that force_domain exists in Redis set before allowing access

### OBSERVATIONS
- **Admin token provides root bypass** (`auth.py:83-86`) — Admin token bypasses ALL domain checks. Can observe any domain via `?domain=other_domain`. Intentional but powerful.
- **Token in query string** (`auth.py:25`) — Allows token via `?token=...` which can leak into logs, URLs, proxies. Should prioritize Authorization header.

**Recommendation:** Document admin token as root-equivalent; log warnings when token extracted from query string.

---

## 2. Redis ACL Model
**Status:** ✓ Reviewed | **Severity:** Low

**Files Reviewed:** `scheduler/utils/redis_acl.py`, `scheduler/api/admin.py`, `scheduler/api/domain.py`, `scheduler/scheduler.py`

### GOOD
- **Tight key patterns** (`redis_acl.py:25-36`) — Worker ACL only grants access to domain-scoped keys: `job_queue:{domain}:*`, `workers:{domain}:*`, etc. Cannot cross-access other domains.
- **Tight channel patterns** (`redis_acl.py:39-43`) — Restricted to `log_stream:{domain}:*` and `job_kill:{domain}` (domain-scoped). Cannot subscribe to other domains.
- **Minimal command whitelist** (`redis_acl.py:46-63`) — Only 13 commands allowed (no KEYS, FLUSHDB, CONFIG, etc.). Commands are read/write ops for queues/state, nothing dangerous.
- **ACL password properly masked in list operations** (`admin.py:70`) — GET /admin/domains returns only username, not password.
- **ACL password only returned on rotate/create** (`admin.py:106, 184; domain.py:89`) — Returns full redis_acl dict only when needed for initial setup.
- **No password in logs** — `scheduler.py:529` logs ACL failures without including password or sensitive details.
- **ACL reconciliation idempotent** (`scheduler.py:526`) — Replays persisted passwords after Redis restart without logging them.

### OBSERVATIONS
- **Legacy username cleanup** (`redis_acl.py:84-88`) — Code removes old hashed usernames from previous implementation. Assumes Redis `DELUSER` on non-existent user is gracefully ignored (wrapped in try/except).

**Recommendation:** No immediate issues. ACL model is well-scoped and secrets are properly masked.

---

## 3. Credential Handling
**Status:** ✓ Reviewed | **Severity:** Low

**Files Reviewed:** `scheduler/api/credentials.py`, `scheduler/api/jobs.py`, `worker/executor.py`

### GOOD
- **Credentials write-only via API** (`credentials.py:4-5`) — Secrets are encrypted in Mongo and never returned in responses.
- **List operations never return secrets** (`credentials.py:28-35`) — GET /credentials/ returns only metadata (name, type, dialect, timestamps), not encrypted payload.
- **Job definitions sanitize sensitive fields** (`jobs.py:36-45`) — SQL connection_uri and Kerberos keytab are masked as "********" in API responses.
- **SQL temp files secure** (`executor.py:109`) — Uses `tempfile.mkstemp()` which creates files with mode 0o600 (owner-only access, not world-readable).
- **Kerberos ccache cleanup guaranteed** (`executor.py:499-506`) — `kdestroy` is in a finally block, ensuring cleanup even on exceptions.
- **No keytab paths in logs** — grep found no logging of keytab paths or Kerberos credentials.

### OBSERVATIONS
- **Credentials stored encrypted in Mongo** (`credentials.py:48, 73`) — Uses `encrypt_payload()` utility. Looks robust; keytab/URI secrets never logged.

**Recommendation:** Credential handling is solid. Ensure `encrypt_payload()` uses a strong cipher (AES-256) and the encryption key is properly rotated.

---

## 4. Executor Security
*To investigate: shell injection risks, PAT hygiene, SQL temp file handling, impersonation/Kerberos privilege escalation*

---

## 5. Network/Transport Security
*To investigate: CORS config, HTTPS enforcement, SSE auth, Docker Compose isolation*

---

## 6. Secrets in Deployment Artifacts
*To investigate: hardcoded secrets, default passwords, insecure defaults in .env.example, values.yaml, Dockerfiles*

---

## 7. Dependency/Supply-Chain Risk
*To investigate: outdated/risky dependencies in pyproject.toml, package.json, go.mod*

---

## 8. AI Feature Risk
*To investigate: prompt injection, API key handling, LLM response sanitization*

---

## Summary — Top 5 Priorities
*(To be populated after investigation)*

---
