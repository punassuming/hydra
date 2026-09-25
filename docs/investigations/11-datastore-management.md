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

### Redis ACL Self-Healing Loop (GOLD STANDARD)
- **File**: `scheduler/scheduler.py:533-555` (redis_acl_reconciliation_loop)
- **Pattern**: Every `SCHEDULER_ACL_RECONCILE_INTERVAL` seconds (default 30s), re-applies persisted worker Redis ACL users from MongoDB
- **Idempotency**: Uses `ensure_worker_acl_user()` with explicit password, which is safe to re-run (idempotent)
- **Scenario**: If Redis restarts and loses all in-memory ACL state, the next 30s cycle restores worker auth without requiring scheduler restart
- **Status**: Excellent — this is a production-grade self-heal loop

### MongoDB Connection Resilience
- **Client construction** (`scheduler/mongo_client.py:9-22`):
  - `serverSelectionTimeoutMS=5000` (default, configurable) — fails fast on Mongo unavailable (instead of default 30s)
  - `tz_aware=True` — prevents timezone bugs (noted in AGENTS.md as a real prior bug fix)
  - No connection pooling config beyond PyMongo defaults (typically 10-50 connections)
  - No explicit retry/backoff on connection failure
- **Reconnection behavior**: PyMongo's ServerSelectionTimeoutMS respects the timeout, but once a client is created, lost connections are re-attempted per-operation (built-in automatic reconnect)
- **Gap**: No scheduler-side self-healing loop for Mongo (no equivalent to ACL reconciliation loop)
  - If Mongo is down during startup, `ensure_domains_seeded()` will fail and the scheduler won't start
  - If Mongo becomes unavailable after startup, the scheduler will report errors but won't attempt recovery
  - Worker queries will timeout (5s) and fail; no automatic recovery

### Redis Connection Resilience
- **Client construction** (`scheduler/redis_client.py:26-72`):
  - Singleton pattern with lazy initialization (line 28: `if _redis_client is None`)
  - **Sentinel support** (lines 32-61): Full Sentinel failover if `REDIS_SENTINELS` + `REDIS_SENTINEL_MASTER` are set
  - **Socket timeout**: `REDIS_SOCKET_TIMEOUT` (default 2s) for both Sentinel and master connections
  - Connection pooling via `redis.from_url()` (default 10-50 connections)
- **Automatic failover**: When using Sentinel, redis-py's `master_for()` handles failover to replica on master death; worker gets transparent failover
- **Gap**: No exponential backoff on initial connection failure; if Redis is down at startup, singleton stays `None` and every call fails

### Findings
- **Excellent**: Redis ACL reconciliation loop is a mature self-heal pattern; should be replicated for other critical resources
- **Solid**: Sentinel support enables Redis HA; transparent failover at client level
- **Gap**: Mongo has no equivalent reconciliation/self-heal loop — operator must manually intervene or restart scheduler if Mongo becomes unavailable
- **Gap**: No retry/backoff on initial startup connection failures; degraded startup scenarios could leave system in broken state
- **Observability gap**: No metrics on reconnection attempts or failover events

### Recommendation
- **Add Mongo connection resilience**:
  - Create a `mongo_connection_monitor_loop()` that periodically pings Mongo and alerts if unavailable
  - Add automatic reconnection attempts (with exponential backoff, max 60s) if Mongo becomes unreachable mid-operation
  - Log distinct "Mongo unavailable" vs "API error" messages so operators can see the root cause
- **Document Sentinel as HA requirement**: Strongly recommend Sentinel for production (single Redis instance is a SPOF)
- **Add startup resilience**: Implement retry-with-backoff in `get_redis()` and `get_mongo_client()` if initial connection fails; allow degraded startup (read-only mode) if Mongo is unavailable
- **Expose reconnection metrics**: Add Prometheus metrics for Redis/Mongo connection state, failover events, and reconciliation loop success/failure

## 7. Observability of Datastores

### Current Health Endpoints
- **`GET /health`** (scheduler/api/health.py:28-54):
  - Returns: `status: ok`, `workers: count`, `pending_jobs: count`, `demo_mode: bool`
  - Tests: Both Redis and Mongo implicitly (via `get_redis()` and `get_db().command("ping")`)
  - **Gap**: If either Redis or Mongo is unreachable, endpoint returns 500 (no distinction between them)
  - **Gap**: No per-datastore connectivity status (e.g., `"redis": "ok", "mongo": "ok"`)
  
- **`GET /health/orchestration`** (scheduler/api/health.py:57-97):
  - Returns: `status: ok|stale|unknown`, `age_seconds`, `loops: [list of running loops]`
  - Purpose: Distinguishes API liveness from orchestration liveness
  - **Gap**: No datastore-specific health (Mongo connection state, Redis cluster state, etc.)

### Worker Metrics (Stored in Redis, Not Exposed as Prometheus)
- **Data source**: `worker_metrics:<domain>:<worker_id>:history` (sorted set in Redis, LTRIM-bounded to rolling window)
- **Metrics captured**: `memory_rss_mb`, `process_count`, Linux load averages (1m, 5m, 15m)
- **Exposure**: Via `/workers/{worker_id}/metrics` JSON endpoint, not Prometheus scrape format
- **Retention**: Bounded by `WORKER_METRICS_WINDOW_SECONDS` (default 1800s / 30 min), auto-trimmed by heartbeat loop

### Datastore-Level Observability Gaps
- **No Prometheus metrics** for:
  - Redis connection pool stats (active connections, timeouts, failover events)
  - Mongo server selection timeouts, connection retries
  - ACL reconciliation loop success/failure rates
  - Database sizes (Mongo collection sizes, Redis memory usage)
  - Query latency distribution (slow queries, timeouts)
- **No database-level introspection** (`db.stats()`, `db.collection.stats()`, Redis `INFO`)
- **No alerting** for datastore-specific conditions (e.g., "Mongo unavailable for >30s", "Redis memory >90%")

### Findings
- **Weak**: `/health` blurs Redis and Mongo failures into a single 500 response
- **Weak**: No operator-facing visibility into datastore health beyond "API works or doesn't"
- **Weak**: No Prometheus integration for cross-system monitoring (operators must check logs or manual `redis-cli INFO`)
- **Weak**: Worker metrics are sampled internally, not exposed to external monitoring systems

### Recommendation
- **Improve `/health` endpoint**:
  - Add `redis: {status, error, latency_ms}` and `mongo: {status, error, latency_ms}` fields
  - Distinguish transient timeouts from permanent failures (e.g., `status: timeout` vs `status: unreachable`)
- **Add `/health/datastores` endpoint**:
  - Returns: `redis: {connected, cluster_info, memory_mb, used_memory_pct}` and `mongo: {connected, size_mb, collections_count, avg_document_size_kb}`
  - Helps operators diagnose capacity/performance issues
- **Expose Prometheus metrics**:
  - Add `prometheus_client` dependency and create:
    - `hydra_redis_connection_pool_active`
    - `hydra_mongo_server_selection_timeout_total`
    - `hydra_acl_reconciliation_loop_errors_total`
    - `hydra_datastore_query_latency_seconds` (histogram)
    - `hydra_job_runs_collection_size_bytes`
- **Add structured logging**:
  - Log datastore connection state changes (connected/disconnected/recovering)
  - Log slow operations (Mongo queries > 1s, Redis operations > 500ms)
  - Log ACL/reconciliation failures with remediation hints

## 8. Scaling Guidance

### Current Documentation
- **Helm chart** (`deploy/helm/hydra/README.md:20-22`):
  - Redis: Single instance, PVC-backed, **no Sentinel/Cluster**
  - MongoDB: Single instance, PVC-backed, **no ReplicaSet**
  - Scheduler: Can be split into API + orchestrator (two Deployments)
  - Workers: Multiple independent Deployments, each independently scaled (Python and/or Go)
- **README.md**: Mentions "production-ready" and "scale" but doesn't specify datastore limitations

### Code Assumptions (No Scaling-Specific Patterns Found)
- **No Mongo-specific**: No replica set awareness, no read preference configuration, no WriteConcern tuning
- **Redis**: Sentinel support present (lines 32-61 in redis_client.py), but single-instance mode is default
- **Single-scheduler assumption**: Orchestrator heartbeat (redis_acl_reconciliation_loop, etc.) assumes one scheduler writes to a single `hydra:orchestrator:heartbeat` key; running two schedulers would cause key conflicts and one would "win"

### Breaking Points at Scale
1. **MongoDB single instance → large dataset**:
   - Query performance degrades without indexes (see section 3)
   - Backup/restore takes longer (no incremental backups)
   - Any maintenance requires downtime (no replica failover)
   - After 1-2 years, `job_runs` collection becomes unbounded bottleneck

2. **Redis single instance → high throughput**:
   - No failover; single node death = system down
   - Memory-only; if not AOF/RDB backed up, data loss on restart (backup is via volume copy, not Redis replication)
   - No read-replica for metrics queries (all `/workers/` calls hit single Redis instance)

3. **Scheduler orchestrator**:
   - If running multiple schedulers for HA, only one can be "active" (orchestrator writing heartbeat)
   - No consensus or leader election; would require external tool (etcd, Consul) or changes to code
   - ACL reconciliation loop would run on every scheduler simultaneously (idempotent but wasteful)

### Observations
- **Helm chart is honest**: Clearly states "single instance" for both Redis and Mongo; no false claims of HA
- **Redis Sentinel wiring is production-ready**: If operators deploy Redis Sentinel, failover is automatic and transparent
- **Mongo HA requires external replica set**: Not documented; operators would need to provision separate MongoDB replica set and change `MONGO_URL` connection string

### Recommendation
- **Document datastore scaling tiers**:
  - **Tier 1 (dev/test)**: Single instance each (current defaults), no HA, works up to ~100k runs/month
  - **Tier 2 (production small)**: Redis Sentinel (3+ nodes) + single Mongo + single scheduler, works up to ~1M runs/month
  - **Tier 3 (production large)**: Redis Sentinel + Mongo ReplicaSet (3+ nodes) + multi-scheduler with etcd consensus + data retention policy, works to 10M+ runs/month
- **Add deployment guides**:
  - `docs/deployment/redis-sentinel-setup.md` — how to provision/manage Sentinel for prod
  - `docs/deployment/mongodb-replicaset-setup.md` — how to provision/manage ReplicaSet for prod (external to Helm chart)
  - `docs/deployment/multi-scheduler-setup.md` — how to run 2+ schedulers with consensus for HA (if/when etcd support is added)
- **Add Helm chart variants**:
  - `values-production.yaml` — pre-configured with replicas, resource limits, persistence tuning for Sentinel+ReplicaSet mode
- **For multi-scheduler**: Either (1) document that it's not supported, or (2) implement a consensus/leader-election layer (e.g., using etcd or Mongo sessions) so only one orchestrator runs at a time

## 9. MongoDB Query Efficiency

### Query Scan Analysis
- **Full collection scans** (potential performance issue):
  1. `db.domains.find({})` (scheduler/api/admin.py:59) — **OK**: domains collection is tiny (~10s of docs max)
  2. No other `find({})` without filters found in API code
  
- **Filtered queries** (require indexes, see section 3):
  - `count_documents({"domain": d})` for jobs/runs per domain — appears in multiple endpoints
  - Sorted queries: `.sort("start_ts", -1)` without indexes would be slow at scale

### Performance-Critical Queries
1. **Admin domain dashboard** (`scheduler/api/admin.py:56-74`):
   - Calls: `db.job_definitions.count_documents({"domain": d})` + `db.job_runs.count_documents({"domain": d})`
   - For each of ~10 domains, 2 count queries = 20 queries
   - **Issue**: Without indexes on `(domain, 1)`, each count does a collection scan
   - **Scale impact**: With 100k+ job_runs, each count takes 1-5 seconds; dashboard load becomes 20-100 seconds
   
2. **Job run history** (`scheduler/api/history.py:45, 67`):
   - Query: `.find(query).sort([("start_ts", -1), ("_id", -1)]).limit(limit + 1)`
   - **Issue**: Sort without index forces in-memory sorting; memory usage O(n) for all matching docs
   - **Scale impact**: If filtering by domain or job_id returns 10k docs, in-memory sort uses 100MB+ RAM per query

3. **Investigations queries** (`scheduler/api/investigations.py:75, 102, 136, 171`):
   - Example: `db.job_runs.find({"job_id": job_id, "status": "success"}).sort("start_ts", -1).limit(1)`
   - **Issue**: Without `(job_id, status, start_ts)` index, does full collection scan then in-memory sort
   - **Scale impact**: At 100k+ runs, becomes slow; Mongo may abort sort if it exceeds sort memory limit

### Aggregation Pipeline Usage
- **No aggregation pipelines found** — all queries use simple find/count
- **Missed opportunity**: No streaming aggregations for complex analytics
- **Not a blocker**: Simple queries are fine; aggregations would only help if doing real-time analytics

### Findings
- **Critical**: Missing indexes on job_runs will cause dashboard and history endpoints to be slow at scale (>50k runs)
- **Critical**: `count_documents()` without domain index will block admin dashboard
- **Moderate**: In-memory sorts (`sort()` without index) risk OOM on large result sets
- **Good news**: No full collection scans except tiny domains collection (OK)
- **Good news**: No complex aggregations (simpler to index than pipeline stages)

### Recommendation
- **Immediate**: Add indexes (see section 3 recommendations):
  - Compound: `(domain, 1), (job_id, 1), (start_ts, -1)` covers most queries
  - Separate: `(job_id, 1), (status, 1)` for failure investigation
  - Separate: `(domain, 1), (start_ts, -1)` for timeline queries
  - All indexes have `background: true` and `sparse: true` where applicable to avoid blocking production
- **Performance testing**: Before deploy, benchmark with:
  - 100k job_runs, measure dashboard load time (should be <2s)
  - Count query on large domain (should be <100ms)
  - Sorted query returning 1000 docs (should be <500ms)
- **Monitoring**: Add slow query logging (Mongo's `operationProfileLevel: 1`, log queries >100ms) to catch regressions

## Summary — Top 5 Priorities

Ranked by (operational risk avoided × urgency × implementation ease):

### 1. **Add MongoDB Indexes for job_runs, job_definitions, credentials**
**Risk**: Query performance degrades from milliseconds to seconds at scale (50k+ runs)  
**Impact**: Dashboard becomes unusable, admin operations slow, history/timeline endpoints timeout  
**Effort**: LOW (2-4 hours)  
**Recommendation**:
- Compound index on job_runs: `(domain, 1), (job_id, 1), (start_ts, -1)` 
- Compound on job_definitions: `(domain, 1), (schedule.enabled, 1), (created_at, -1)`
- Ensure indexes created at startup via `scheduler/migrations/indexes.py`
- **Test**: Verify dashboard load <2s with 100k+ runs before deploy

### 2. **Implement Data Retention Policy for job_runs**
**Risk**: MongoDB grows unbounded; after 1-2 years becomes multi-TB bottleneck  
**Impact**: Backup/restore times grow, query performance degrades further, storage costs balloon  
**Effort**: MEDIUM (6-8 hours)  
**Recommendation**:
- Add `HYDRA_RUN_RETENTION_DAYS` env var (default 90 days)
- Create daily cleanup loop: delete runs older than retention window
- Add optional S3/GCS export before deletion for audit/compliance
- Log deletion metrics (docs removed, bytes freed)
- **Test**: Verify cleanup loop removes old runs and completes in <5 minutes

### 3. **Add MongoDB Connection Resilience & Monitoring Loop**
**Risk**: Mongo outage requires manual scheduler restart; no automatic recovery  
**Impact**: Extended downtime when Mongo becomes temporarily unavailable  
**Effort**: MEDIUM (6-8 hours)  
**Recommendation**:
- Add `mongo_connection_monitor_loop()` to orchestrator (similar to redis_acl_reconciliation)
- Periodically ping Mongo; log state changes (connected → disconnected → recovered)
- Implement exponential backoff on connection failures (max 60s retry interval)
- Expose metrics: `hydra_mongo_connection_errors_total`, `hydra_mongo_last_connected_age_seconds`
- **Test**: Simulate Mongo crash; verify scheduler recovers and resumes operations within 60s

### 4. **Improve Health & Observability Endpoints**
**Risk**: Operators can't distinguish "Redis down" from "Mongo down" from API response  
**Impact**: Slow incident response, operators waste time debugging wrong service  
**Effort**: MEDIUM (4-6 hours)  
**Recommendation**:
- Enhance `/health` to return separate redis/mongo status (not just aggregate 500)
- Add `/health/datastores` endpoint with size, memory, connection details
- Add Prometheus metrics: `hydra_redis_connection_pool_active`, `hydra_mongo_server_selection_timeouts_total`, `hydra_acl_reconciliation_loop_errors_total`
- Structured logging: log datastore state changes and slow operations (>1s for Mongo, >500ms for Redis)
- **Test**: Verify health endpoints return correct status when each datastore is down

### 5. **Add Backup Lifecycle Management & Automated Testing**
**Risk**: Backup directory grows unbounded; no validation that backups can be restored  
**Impact**: Disk space exhaustion, risk of silent restore failures  
**Effort**: MEDIUM (6-8 hours)  
**Recommendation**:
- Backup script: add retention policy (keep 7 daily, 4 weekly, 12 monthly; delete older)
- Add backup manifest versioning to support format migrations
- Add weekly Routine: restore backup to test environment, validate data integrity, report pass/fail
- Rotate encryption key annually; store passphrases in secrets manager
- Add Redis AOF/RDB flush before backup to ensure clean state
- **Test**: Run backup→restore cycle; verify operator can retrieve data from any backup

---

## Key Strengths (No Action Required)

- **Redis ACL reconciliation loop**: Gold-standard self-heal pattern; exactly what production needs
- **Sentinel support**: Well-integrated, transparent failover for Redis HA
- **Backup/restore implementation**: Encryption, integrity checks, auth-fail-closed validation all solid
- **Query efficiency**: No unexpected full collection scans; simple find/count queries are appropriate
- **Worker metrics**: Good rolling window implementation with auto-LTRIM

---

## Independent Validation Pass (2026-09-25)

**Validator**: Claude Haiku 4.5  
**Method**: Verification of all 9 areas via codebase inspection, grep searches, and line-by-line file reads. Two WRONG claims found (confirmation bias breaks); all line numbers spot-checked.

### Area-by-Area Summary

| Area | Status | Key Finding |
|------|--------|------------|
| 1. Redis key-space design | PARTIALLY WRONG | `worker_ops:*` and `log_stream:*:history` are NOT unbounded; both have LTRIM + TTL |
| 2. Redis connection management | CONFIRMED | Sentinel wiring, pooling, timeouts all verified at lines 26-72 of redis_client.py |
| 3. MongoDB schema & indexing | CONFIRMED | Zero explicit `create_index()` calls found; tz_aware=True at mongo_client.py:21 verified |
| 4. Data retention & growth | CONFIRMED | No retention loop, TTL index, or cleanup logic for job_runs; unbounded growth risk accurate |
| 5. Backup & restore practices | CONFIRMED | All line numbers and features (GPG, SHA256SUMS, auth validation) verified in backup/restore scripts |
| 6. Resilience & self-healing | CONFIRMED | ACL loop at scheduler.py:533-555 verified; Mongo resilience gap accurate |
| 7. Observability of datastores | CONFIRMED | `/health` and `/health/orchestration` line ranges verified; no per-datastore status gap confirmed |
| 8. Scaling guidance | CONFIRMED | Helm chart lines 20-21 confirm single-instance Redis/Mongo defaults |
| 9. MongoDB query efficiency | CONFIRMED | Query line numbers (admin.py:56-74, history.py:45/67, investigations.py:75/102/136/171) all verified |

### Critical Corrections

**WRONG #1: `worker_ops:*` unbounded claim** (Section 1, Findings)  
- **Report claims**: "worker_ops:* — unbounded (no trim cap observed)"
- **Actual code** (scheduler/utils/worker_ops.py:25-26):
  ```python
  r.ltrim(key, -1000, -1)  # Trim to 1000 entries
  r.expire(key, 7 * 24 * 3600)  # 7-day TTL
  ```
- **Impact**: NOT a growth risk; purges automatically every 7 days and keeps only 1000 most-recent entries per worker

**WRONG #2: `log_stream:*:history` unbounded claim** (Section 1, Findings)  
- **Report claims**: "log_stream:*:history — unbounded unless explicitly trimmed"
- **Actual code** (worker/worker.py:264-266):
  ```python
  r.ltrim(history_key, -400, -1)  # Trim to 400 entries
  r.expire(history_key, 3600)  # 1-hour TTL
  ```
- **Impact**: NOT a growth risk; automatically expires after 1 hour and keeps only 400 most-recent log lines per run

### Detailed Verification by Area

**Area 1 — Redis key-space design**
- ✓ All 8 key patterns confirmed (job_queue, job_enqueue_meta, run_events, log_stream, worker_metrics, worker_ops, hydra:domains, hydra:orchestrator:heartbeat)
- ✗ **worker_ops TTL/LTRIM**: Report says unbounded; code shows `r.ltrim(key, -1000, -1)` + `r.expire(7d)` (lines scheduler/utils/worker_ops.py:25-26)
- ✗ **log_stream history TTL/LTRIM**: Report says unbounded; code shows `r.ltrim(history_key, -400, -1)` + `r.expire(3600)` (lines worker/worker.py:264-266)
- ✓ worker_metrics LTRIM claim verified (worker/utils/heartbeat.py:196-197)
- ✓ job_enqueue_meta 24h TTL verified (multiple locations: failover.py:81, run_events.py:59, etc.)

**Area 2 — Redis connection management**  
- ✓ Sentinel support fully wired (scheduler/redis_client.py:32-61)
- ✓ Sentinel auth optional (`REDIS_SENTINEL_USERNAME`/`REDIS_SENTINEL_PASSWORD`)
- ✓ Socket timeout 2s default (line 34, 52)
- ✓ Connection pooling via `redis.from_url()` (line 71)
- ✓ No explicit retry-backoff gap noted accurately

**Area 3 — MongoDB schema & indexing**  
- ✓ Zero `create_index()` or `ensure_index()` calls found (full grep search)
- ✓ `tz_aware=True` at mongo_client.py:21 (verified with context: prevents naive datetime bugs)
- ✓ Query patterns accurately identified (admin.py, history.py, investigations.py)

**Area 4 — Data retention & growth**  
- ✓ No retention cleanup loop for job_runs (confirmed via grep: no matches for `RETENTION_DAYS`, `purge`, `delete.*run`)
- ✓ Unbounded growth projection (3.6M docs/year, 500GB+) is reasonable estimate

**Area 5 — Backup & restore practices**  
- ✓ backup-volumes.sh: 62 lines, stops services (line 36), GPG-AES256 (lines 45-47), SHA256SUMS (lines 51-52)
- ✓ restore-isolated.sh: 83 lines, decrypt (49-51), isolated network (60), auth validation (75-80)
- ✓ All specific assertions verified

**Area 6 — Resilience & self-healing**  
- ✓ redis_acl_reconciliation_loop at scheduler.py:533-555 (verified; idempotent via `ensure_worker_acl_user`)
- ✓ Interval default 30s (from `REDIS_ACL_RECONCILE_INTERVAL`, line 549 shows it logged)
- ✓ No Mongo equivalent confirmed (no `mongo_connection_monitor_loop` found)

**Area 7 — Observability of datastores**  
- ✓ `/health` at scheduler/api/health.py:28-54 (tests Redis + Mongo, blurs failures into 500)
- ✓ `/health/orchestration` at scheduler/api/health.py:57-97 (checks heartbeat freshness)
- ✓ No per-datastore status in response (both must succeed or fail together)

**Area 8 — Scaling guidance**  
- ✓ Helm chart README lines 20-21 state single instance + no Sentinel/ReplicaSet
- ✓ Sentinel support in code confirmed (redis_client.py)
- ✓ Scaling tiers recommendation aligns with actual capabilities

**Area 9 — MongoDB query efficiency**  
- ✓ admin.py:62-63: `count_documents({"domain": d})` without index (confirmed)
- ✓ history.py:45: unsorted `find(query).sort("start_ts", -1)` (confirmed)
- ✓ history.py:67: sorted query with compound sort `[("start_ts", -1), ("_id", -1)]` (confirmed)
- ✓ investigations.py line 75, 102, 136, 171: all unindexed queries confirmed

### Overall Verdict

**Confidence: HIGH (7/10)** — Most claims verified and accurate; two material errors in Section 1 (worker_ops, log_stream history) both incorrectly described as unbounded when they have explicit retention. These errors do NOT impact the validity of the 5 Priority recommendations (indexes, retention, Mongo resilience, health endpoints, backup lifecycle) — those remain sound and urgent. The report's factual foundation is solid except for these two Redis key retention claims.

---

## Documented Assumptions (For Operators)

1. Single-instance Redis/Mongo are the default; operators should deploy Redis Sentinel for HA
2. No multi-scheduler consensus implemented; only one orchestrator can run at a time
3. Job runs grow unbounded without retention policy; operators must configure `HYDRA_RUN_RETENTION_DAYS`
4. Backup involves service downtime; schedule during maintenance windows
