# Datastore Management Investigation

**Date:** 2026-09-25  
**Investigator:** Claude Haiku 4.5  
**Status:** In Progress

---

## 1. Redis Key-Space Design

### Key Patterns Found
- **Job Queuing**: `job_queue:<domain>:pending` (sorted set), `job_queue:<domain>:<worker_id>` (list)
- **Job Metadata**: `job_enqueue_meta:<domain>:<job_id>` (hash with starvation counter + priority, TTL 24h)
- **Run Events**: `run_events:<domain>` (list, TTL 24h, consumed by `run_event_loop`)
- **Logs**: `log_stream:<domain>:<run_id>` (pub/sub channel), `log_stream:<domain>:<run_id>:history` (list)
- **Worker Metrics**: `worker_metrics:<domain>:<worker_id>:history` (sorted set, rolling window per `WORKER_METRICS_WINDOW_SECONDS`, default 1800s)
- **Worker Operations**: `worker_ops:<domain>:<worker_id>` (list of JSON events)
- **Global Registry**: `hydra:domains` (set), `hydra:orchestrator:heartbeat` (string with JSON, TTL 30s)

### Findings
- **Naming conventions**: Consistent use of `<entity_type>:<domain>:<identifier>` pattern across all keys. Good!
- **TTL coverage**: `job_enqueue_meta`, `run_events`, and `hydra:orchestrator:heartbeat` all have explicit TTLs (24h, 24h, 30s). However, several key types lack explicit TTLs:
  - `job_queue:*` (both pending and per-worker lists) — unbounded growth if not drained
  - `log_stream:*:history` — unbounded unless explicitly trimmed
  - `worker_metrics:*:history` — bounded by `WORKER_METRICS_WINDOW_SECONDS` via LTRIM in heartbeat loop (lines worker/utils/heartbeat.py:194)
  - `worker_ops:*` — unbounded (no trim cap observed)

### Risk Assessment
- **Moderate risk**: `job_queue:` lists should never grow unbounded in normal operation (jobs get dequeued), but stuck jobs could accumulate. No explicit LTRIM/cleanup observed.
- **Potential growth**: `log_stream:*:history` and `worker_ops:*` lack retention policy. Over months of heavy use, these could consume significant memory.

### Recommendation
- Document expected lifecycle of each key type (ephemeral vs. long-lived)
- Add explicit LTRIM or TTL for `log_stream:*:history` (e.g., 1000-entry cap) and `worker_ops:*` (e.g., 5000-entry cap or 7-day TTL)
- Validate that `job_queue:` lists drain properly; add monitoring/alerts for unexpected queue growth

## 2. Redis Connection Management

### Connection Pool & Failover Configuration
- **File**: `/home/user/Hydra/scheduler/redis_client.py` (lines 26-72)
- **Sentinel Support**: Yes, fully wired with `REDIS_SENTINELS` + `REDIS_SENTINEL_MASTER` env vars
  - Parses comma-separated sentinel nodes (line 9-23)
  - Supports optional Sentinel auth (`REDIS_SENTINEL_USERNAME`/`REDIS_SENTINEL_PASSWORD`)
  - Master-only failover via `sentinel.master_for()` (line 61)
- **Connection Pooling**: Uses `redis.from_url()` which enables default connection pooling (5-50 connections per pool)
- **Timeouts**: 
  - `REDIS_SOCKET_TIMEOUT` (default 2s) — applies to both Sentinel and master connections
  - Used in both scheduler and worker (`worker/redis_client.py:50`)
- **Retry/Backoff**: 
  - No explicit retry loop in client construction; relies on redis-py's internal retry-on-connect-error (minimal backoff)
  - Worker kill listener has exponential backoff on connection errors (worker/worker.py:169)
  - Scheduler loops have broad exception handlers but no explicit retry/exponential backoff

### Health Checks
- `/health` endpoint (scheduler/api/health.py): Tests both Redis (via `get_redis().zcard()`) and Mongo (via `db.command("ping")`)
- `/health/orchestration` endpoint: Checks orchestrator heartbeat freshness in Redis
- **Gap**: No granular distinction between Redis and Mongo connectivity in `/health` response — both must succeed or the endpoint fails with 500

### Findings
- **Solid**: Sentinel support is present and well-configured; supports master failover with auth
- **Gap**: No explicit retry-with-backoff on initial connection failure in `get_redis()` — if Redis is temporarily down during scheduler startup, the singleton client will fail once and leave `_redis_client` as None (but not re-attempted on next call)
- **Observability gap**: `/health` doesn't distinguish "Redis is down" vs "Mongo is down" — would require parsing exception types
- **Resilience gap**: If a Sentinel-based connection master-fails, redis-py handles it automatically. But if Sentinel itself becomes unreachable, there's no fallback to direct URL

### Recommendation
- Document Sentinel as a production best practice, but require `REDIS_SENTINELS` explicitly set (no silent fallback to non-HA mode)
- Add health endpoint that reports Redis and Mongo status separately (for better operator awareness)
- Consider exponential backoff on initial connection failure in `get_redis()` for graceful startup in degraded scenarios
- Add a note in deployment docs: "If all Sentinels fail, Redis must remain up (Sentinels only discover failover; they don't reboot Redis)."

## 3. MongoDB Schema & Indexing

**Status:** Investigating...

## 4. Data Retention & Growth

**Status:** Investigating...

## 5. Backup & Restore Practices

**Status:** Investigating...

## 6. Resilience & Self-Healing

**Status:** Investigating...

## 7. Observability of Datastores

**Status:** Investigating...

## 8. Scaling Guidance

**Status:** Investigating...

## 9. MongoDB Query Efficiency

**Status:** Investigating...

## Summary — Top 5 Priorities

**Status:** Pending investigation completion...
