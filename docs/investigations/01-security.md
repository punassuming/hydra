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
*To investigate: worker ACL channel patterns, credential rotation, secret masking in responses*

---

## 3. Credential Handling
*To investigate: storage/masking of Kerberos keytabs, SQL URIs, secrets in logs/API responses/job definitions*

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
