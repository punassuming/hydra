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

### Current State
- **No explicit index creation found** — grepping for `create_index()`, `ensure_index()` yields nothing in the codebase
- **tz_aware=True fix applied** (scheduler/mongo_client.py:21) — prevents naive datetime decoding bugs noted in AGENTS.md

### Identified Query Patterns & Missing Indexes
**job_runs collection** (heavily queried, unbounded growth):
- Filters: `_id` (PK, auto-indexed), `job_id`, `status`, `domain`, `worker_id`, `run_id`
- Sorts: `start_ts` (most common), also `[("start_ts", -1), ("_id", -1)]`
- Queries missing indexes (full collection scans on large datasets):
  - `{"job_id": X}` (multiple sorts/finds, scheduler/api/jobs.py:525, investigations.py:102, etc.) — **NEEDS INDEX: (job_id, 1)**
  - `{"job_id": X, "status": Y}` (investigations.py:102, 136, 165, 168) — **NEEDS INDEX: (job_id, 1), (status, 1)** or compound
  - `{"domain": X}` (scheduler.py:452, admin.py:63, jobs.py:516) — **NEEDS INDEX: (domain, 1)**
  - `{"start_ts": ...}` when sorted/ranged — **NEEDS INDEX: (start_ts, 1) or (start_ts, -1)**
- Count aggregations across all runs (admin.py:63, jobs.py:975-977) will scan entire collection

**job_definitions collection**:
- Filters: `_id` (PK), `domain`, `name`, `schedule.mode`, `schedule.enabled`
- Sorts: `created_at`, `_id`
- Missing indexes:
  - `{"domain": X}` (multiple places) — **NEEDS INDEX: (domain, 1)**
  - `{"domain": X, "schedule.mode": Y}` (jobs.py:961) — **NEEDS COMPOUND INDEX**
  - `{"name": X, "domain": X}` (admin.py:205) — **NEEDS COMPOUND INDEX**

**credentials collection**:
- Filters: `name`, `domain`
- Missing indexes: `{"name": X, "domain": X}` — **NEEDS COMPOUND INDEX**

### Risk Assessment
- **High risk**: `job_runs` queries are the most performance-critical; with 10k+ runs/day, unindexed job_id lookups will degrade from milliseconds (indexed) to seconds (scan)
- **Medium risk**: `/admin/domains` stats aggregation (count_documents across all runs) will be O(n) scans, slow at scale
- **Startup cost**: Every deploy/restart incurs the first query penalty for each unindexed field

### Recommendation
- **Immediate**: Add compound index on `job_runs` for common filter+sort: `(domain, 1), (job_id, 1), (start_ts, -1)`
- **Add**: `(job_id, 1), (status, 1)` for failure investigation queries
- **Add**: `(domain, 1), (start_ts, -1)` for timeline/history queries
- **job_definitions**: Compound index `(domain, 1), (schedule.enabled, 1), (created_at, -1)`
- **credentials**: Compound index `(domain, 1), (name, 1)`
- Create a `scheduler/migrations/indexes.py` module that runs on startup to idempotently ensure indexes exist (uses `create_index(..., unique=False)` which is safe to re-run)

## 4. Data Retention & Growth

### Current Policy
- **No MongoDB job_runs retention/cleanup**: job_runs collection grows indefinitely; no TTL index, no archival job, no deletion logic observed
- **Compare to Redis**: Worker registry records are pruned after `SCHEDULER_WORKER_OFFLINE_PRUNE_SECONDS` (default 1800s / 30 min); explicitly comparable cleanup exists for Redis but NOT Mongo
- **job_definitions**: Persisted indefinitely (expected behavior — jobs are definitions, not runs)
- **credentials**: Persisted indefinitely (expected behavior)
- **domains**: Persisted indefinitely (expected behavior)

### Projection: Unbounded Growth Risk
With 10k runs/day (small-to-medium deployment):
- Year 1: ~3.6M documents, ~500GB+ (depending on log detail captured in run metadata)
- Year 2: ~7.2M documents, ~1TB+
- **Impact**: Queries slow, backups grow, storage costs scale linearly, vacuum/defragmentation becomes necessary

### Backup & Restore Practices
- **File**: `deploy/compose/scripts/backup-volumes.sh` (lines 1-62)
  - Uses raw volume copy (tar) while services are stopped (line 36 `docker compose stop`)
  - Encrypted with GPG-AES256 (lines 45-47)
  - Creates MANIFEST with source_commit, created_utc, format
- **Consistency**: Backup is consistent (services are stopped), but provides no point-in-time recovery — just full volume snapshots
- **Restore** (`restore-isolated.sh` implied but not provided in grep): Would restore raw volumes without MongoDB journal replay risk (since volumes were stopped cleanly)

### Findings
- **Critical gap**: No data retention policy for MongoDB. After 1-2 years of production, query performance will degrade unless archived/purged
- **Moderate gap**: No incremental or point-in-time backup capability; only full volume snapshots
- **Backup maturity**: Encryption and validation (SHA256SUMS) are present, but lifecycle management (retention, deletion, rotation) not evident
- **No archival tooling**: No script to export old runs to a data lake (S3, GCS, etc.) before deleting

### Recommendation
- **Immediate**: Implement a `scheduler/maintenance/retention.py` job that:
  - Runs daily and deletes job_runs older than N days (configurable, e.g., 90 days default via `HYDRA_RUN_RETENTION_DAYS`)
  - Offers an optional pre-deletion archive step (export to S3 if `HYDRA_ARCHIVE_BUCKET` is set)
  - Logs how many documents were purged
- **Medium-term**: Add a `/admin/maintenance/runs/archive` endpoint to manually export/purge runs for a date range
- **Document**: Clearly state in deployment README that operators must configure `HYDRA_RUN_RETENTION_DAYS` for production; recommend 90-180 days
- **Optional**: Add a MongoDB TTL index on `start_ts` field as a safety net (TTL 180 days) so even if cleanup loop fails, old runs eventually age off

## 5. Backup & Restore Practices

### Backup Implementation
- **Script**: `deploy/compose/scripts/backup-volumes.sh` (62 lines)
- **Method**: Raw volume copy (tar) of named volumes `hydra_mongo-data` and `hydra_redis-data`
- **Consistency**: Achieved by stopping all services before backup (line 36: `docker compose stop`)
- **Encryption**: GPG-AES256 symmetric encryption (line 45-47)
- **Integrity**: SHA256SUMS file for checksum validation (line 51-53)
- **Metadata**: MANIFEST file includes source_commit, created_utc, format version (lines 54-59)

### Restore Implementation
- **Script**: `deploy/compose/scripts/restore-isolated.sh` (83 lines)
- **Isolation**: Restores into a temporary network with clean volumes (no production interference)
- **Process**:
  1. Decrypt backup tar files using GPG (lines 49-51)
  2. Create isolated volumes and network (lines 53-60)
  3. Launch test Mongo and Redis in isolation with auth enabled (lines 61-64)
  4. Validate connectivity and auth-fail-closed behavior (lines 66-80)
  5. Return pass/fail signal
- **Validation**: Checks that Mongo/Redis require auth (lines 75-80) — prevents corrupted/unauthenticated restore

### Findings
- **Strengths**:
  - Encryption and integrity checks (GPG + SHA256)
  - Isolation testing prevents silent restore failures
  - Auth-fail-closed validation is thorough (lines 75-80)
  - Metadata tracking (source_commit) aids audit/compliance
- **Gaps**:
  - **No Redis persistence verification**: Backup copies raw volume, but Redis AOF/RDB state is not independently validated before encrypt
  - **No Mongo journal recovery**: If Mongo was mid-write when stopped, restoration relies on Mongo's journal (implicit, not validated)
  - **No point-in-time recovery**: Only full-volume snapshots; incremental or binary logs not captured
  - **No versioned retention**: Script doesn't manage backup lifecycle (rotation, deletion, expiry)
  - **Single encryption key**: No key rotation; same passphrase for all backups (compromised key ⇒ all backups exposed)
  - **Manual restore only**: No restore automation; requires operator to run script manually
- **Operational risk**:
  - Backup creation stops ALL services (downtime ~1-5 min depending on volume size)
  - No parallel backup during maintenance window (could be added)
  - No bandwidth/disk-space limits in backup script

### Recommendation
- **Document clearly**: Backup involves service downtime; schedule during maintenance windows
- **Add backup lifecycle**:
  - Retention policy: keep last 7 daily + 4 weekly + 12 monthly backups (configurable)
  - Automatic deletion of backups older than retention window
  - Manifest versioning to support different restore formats
- **Redis persistence**: Before backup, flush Redis AOF/RDB to ensure clean state (add `bgrewriteaof` call in backup script)
- **Incremental backup option**: For large Mongo volumes, add a mode that exports/archives old runs first, reducing backup size
- **Separate encryption keys**: Rotate backup encryption key annually; store passphrases in secrets manager (HashiCorp Vault, AWS Secrets Manager, etc.)
- **Automated restore testing**: Add a Routine (scheduled trigger) that weekly restores to a test environment and validates data integrity

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
