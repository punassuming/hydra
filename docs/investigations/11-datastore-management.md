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

**Status:** Investigating...

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
