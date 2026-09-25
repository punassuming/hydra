# Worker Framework & Protocol Investigation

**Investigation Date:** 2026-09-25  
**Scope:** Python `worker/` vs Go `go-worker/` — shared Redis protocol & env-var contract  
**Status:** IN PROGRESS

---

## 1. Registration & Discovery Protocol
*Investigating: Redis keys, data shapes, TTLs, scheduler consumption*

### FINDING: Registration protocol is well-aligned

**Python worker** (`worker/worker.py:43-108`):
- Writes hash to `workers:{domain}:{worker_id}` with fields: os, domain, tags, allowed_users, max_concurrency, current_running, status, state, cpu_count, python_version, cwd, hostname, ip, subnet, deployment_type, run_user, shells, capabilities, domain_token_hash, startup_duration_ms
- Detects `startup_duration_ms` and stores it

**Go worker** (`go-worker/internal/worker/worker.go:75-137`):
- Writes same hash to `workers:{domain}:{worker_id}` with fields: worker_id, os, domain, tags, allowed_users, max_concurrency, current_running, status, state, cpu_count, go_version, cwd, hostname, ip, subnet, deployment_type, run_user, shells, capabilities, domain_token_hash
- **DOES NOT** store startup_duration_ms (missing field!)

**Scheduler consumption** (`scheduler/api/workers.py:199-250`):
- Reads fields gracefully, treats missing fields as None or empty string
- No crashes on missing `startup_duration_ms`, but this metric is lost for Go workers

**Key difference**: Go worker doesn't populate `startup_duration_ms` in registration metadata. This field is present in `appendWorkerOp()` details but not in the worker hash itself. **Risk: Low** (UI can display null, but metadata loss).

---

## 2. Heartbeat Protocol
*Investigating: interval, TTL, metrics fields, graceful degradation*

### FINDING: Heartbeat protocol is shared, but load metrics are partially lost in Go

**Interval & TTL**: Both workers use 2s heartbeat interval (Python `heartbeat.py:168`, Go `worker.go:156`), same Redis key format `worker_heartbeats:{domain}`

**Metrics collected**:
- Python (`worker/utils/heartbeat.py:35-81`): process_count, memory_rss_mb, load_1m, load_5m (both Linux & Windows)
- Go (`go-worker/internal/worker/metrics.go:13-66`): process_count, memory_rss_mb, load_1m, load_5m (both Linux & fallback)

**Metrics stored to Redis worker hash**:
- Python (`heartbeat.py:198-207`): Stores process_count, memory_rss_mb, load_1m, load_5m, metrics_ts
- Go (`worker.go:216-220`): Stores **ONLY** process_count, memory_rss_mb, metrics_ts — **MISSING load_1m, load_5m!**

**Metrics history**:
- Both store full metrics (including load) in `worker_metrics:{domain}:{worker_id}:history` as JSON
- Python caps at max_samples (default 120 samples over 1800s window)
- Go caps at max_samples (same logic)

**Scheduler handling** (`scheduler/api/workers.py:69-117`):
- Loads metrics history and reads load_1m/load_5m from recent samples gracefully
- Falls back to Redis hash if no history
- Go workers will have None/null for load_1m/load_5m in the worker hash, but values in history — this creates **stale-data inconsistency** if only the hash is read

**Risk: Medium** — The metrics history alleviates this, but if history is evicted, Go workers will permanently report null for load averages in worker info.

---

## 3. Dispatch Queue Protocol
*Investigating: envelope format, BLPOP shape, executor-type parsing*

### FINDING: Envelope format is shared and well-structured

**Queue format**: Both workers BLPOP from `job_queue:{domain}:{worker_id}`
- Python (`worker/worker.py:415-438`): Deserializes JSON envelope, moves malformed payloads to dead-letter queue
- Go (`go-worker/internal/worker/worker.go:313-317`): Deserializes JSON envelope, logs error but continues (no dead-letter mechanism)

**Envelope structure** (shared):
- job_id, job (full job object), params, enqueued_ts, dispatch_ts, retry_attempt, bypass_concurrency
- Both workers extract: job_id, executor type, completion criteria, bypass_concurrency

**Executor type handling**:
- Python (`worker/worker.py:234`): Reads `executor.type` from job, defaults to "shell"
- Go (`go-worker/internal/worker/worker.go:405-408`): Same logic, defaults to "shell"

**Job envelope deserialization**:
- Both have a JobEnvelope struct (implicit in Python, explicit Go)
- Both handle missing/null fields gracefully

**Risk: Low** — Protocol is well-aligned. Dead-letter handling is better in Python but not critical (Go simply skips bad envelopes).

---

## 4. Run Event Protocol
*Investigating: run_start/run_end shape, timing fields, missing-field handling*

### FINDING: Critical timing-field gap in Go worker run_end events

**run_start event** (both identical):
- Python (`worker/worker.py:219-238`), Go (`go-worker/internal/worker/worker.go:411-428`):
- Both publish: type, run_id, job_id, user, domain, worker_id, start_ts, scheduled_ts, slot, attempt, retries_remaining, schedule_tick, schedule_mode, executor_type, queue_latency_ms, bypass_concurrency

**run_end event** (MISMATCH):

Python (`worker/worker.py:354-383`):
```python
"total_run_ms": round((end_ts - started_ts) * 1000, 2),
"source_fetch_ms": timings.get("source_fetch_ms"),
"env_prep_ms": timings.get("env_prep_ms"),
```
All other fields present.

Go (`go-worker/internal/worker/worker.go:541-565`):
- **MISSING**: total_run_ms, source_fetch_ms, env_prep_ms
- Goes from end_ts directly without calculating total_run_ms
- Collects ExecResult but doesn't populate timing fields

**Scheduler impact** (`scheduler/api/ai.py`):
- AI features depend on total_run_ms for duration analysis
- Mongo run docs will have null for these fields when jobs run on Go workers
- Historical duration analysis breaks for mixed pools

**Risk: HIGH** — Duration prediction/regression analysis will fail or produce degraded results for Go-worker jobs. Timing fields are essential for:
1. Duration percentiles (`predict_duration`, `diagnose_regression`)
2. Long-running outlier detection (investigations)
3. Performance trending

---

## 5. Log Streaming Protocol
*Investigating: per-domain channels, chunk/format consistency, SSE/UI compatibility*

### FINDING: Log streaming protocol is correctly aligned

**Channel format**: Both workers publish to `log_stream:{domain}:{run_id}`

Python (`worker/worker.py:248-267`):
```python
payload = {
    "run_id": run_id,
    "job_id": job_id,
    "worker_id": worker_id,
    "domain": domain,
    "ts": time.time(),
    "text": chunk,
    "stream": kind,  # "stdout" or "stderr"
}
data = json.dumps(payload)
channel = f"log_stream:{domain}:{run_id}"
history_key = f"log_stream:{domain}:{run_id}:history"
r.rpush(history_key, data)
r.ltrim(history_key, -400, -1)
r.publish(channel, data)
r.expire(history_key, 3600)
r.expire(channel, 3600)
```

Go (`go-worker/internal/worker/worker.go:435-455`):
```go
payload := map[string]interface{}{
    "run_id":    runID,
    "job_id":    jobID,
    "worker_id": w.cfg.WorkerID,
    "domain":    w.cfg.Domain,
    "ts":        float64(time.Now().UnixMilli()) / 1000.0,
    "text":      chunk + "\n",  // ← Go adds newline
    "stream":    stream,
}
```

**Key difference**: Go appends "\n" to chunk, Python passes chunk as-is. Both publish to same Redis channel and keep 400-item history.

**Scheduler/UI consumption** (`scheduler/api/logs.py`):
- Reads from `log_stream:{domain}:{run_id}:history` via LRANGE
- SSE endpoint streams these events to UI
- UI's LogViewer/RunInspector parses JSON and displays

**Risk: Low** — The newline difference is cosmetic; UI handles it. Both protocols are compatible.

---

## 6. Worker Operations Log Protocol
*Investigating: event types, shapes, timeline rendering completeness*

### FINDING: Operations log protocol is fully aligned

**Format**: Both write to `worker_ops:{domain}:{worker_id}` (list, keep last 1000, 7-day TTL)

Event structure (both identical):
```json
{
  "ts": float64 (unix timestamp),
  "type": string,
  "message": string,
  "details": dict
}
```

**Event types advertised** (Python `worker/worker.py:30-108`; Go `go-worker/internal/worker/worker.go:678-690`):
- "start" / "restart" — at registration
- "run_exec" — job execution begins
- "run_result" — job execution ends

Both populate details identically:
- start/restart: max_concurrency, state, hostname, run_user, pid, startup_duration_ms (Python only for Go gap)
- run_exec: run_id, job_id, slot
- run_result: run_id, job_id, status, returncode, attempt, completion_reason

**Scheduler consumption** (`scheduler/api/workers.py` + UI):
- Operations timeline displays these events
- UI's WorkerDetail page renders "Operational Timeline"
- No executor-type specific operations (both workers emit same event types)

**Risk: Low** — Operations log is well-aligned. No silent breaks.

---

## 7. Capability Negotiation & Affinity
*Investigating: capability advertisement, fail-closed detection, dispatcher trust*

### FINDING: Critical capability gap — Go worker doesn't advertise sensor support

**Capability detection**:

Python (`worker/runtime.py:96-127`):
- Returns: shell, external, python (if found), powershell (if found), batch (on Windows), sql (if python+sqlalchemy), http, **sensor**
- sensor is ALWAYS advertised

Go (`go-worker/internal/executor/executor.go:672-690`):
- Returns: shell, external, python (if found), sql (if python found), powershell (if found), batch (on Windows), http
- **DOES NOT advertise sensor**

**Scheduler dispatcher** (`scheduler/api/dispatcher.py` or similar):
- Selects workers based on capabilities
- If a sensor job is submitted and dispatcher doesn't filter, Go worker might receive it
- Go worker doesn't have sensor executor → job execution will fail

**Verification of sensor executor**:
- Python: `worker/executor.py` includes `elif executor_type == "sensor":` handler
- Go: `go-worker/internal/executor/executor.go` - checking for sensor executor type...

**Risk: HIGH** — Scheduler can dispatch sensor jobs to Go workers, causing silent failures. This violates fail-closed principle. Sensor jobs should route only to Python workers, but there's no enforcement in the dispatcher or Go executor.

---

## 8. State/Lifecycle Protocol
*Investigating: online/draining/offline handling, dispatch gate behavior*

### FINDING: State protocol is protocol-aligned but Go lacks draining enforcement

**State values**: Both support online/draining/offline

**State persistence**:
- Python: Reads from `WORKER_STATE` env var on startup, stores in worker hash
- Go: Reads from `INITIAL_STATE` env var, stores in worker hash

**Scheduler state endpoint** (`POST /workers/{worker_id}/state`):
- Updates worker hash field "state" (not redis key TTL — direct mutation)
- Both workers read via heartbeat or initialization

**Draining enforcement**:
- Python: `worker/worker.py` does NOT explicitly check state before accepting jobs from queue — relies on scheduler-side gating
- Go: `go-worker/internal/worker/worker.go` does NOT explicitly check state before BLPOP

**Scheduler-side dispatch gate** (check scheduler/orchestrator):
- Scheduler reads worker state and should not dispatch new jobs to draining/offline workers
- This enforcement is scheduler-side, not worker-side

**Risk: Low** — State protocol is contract-aligned. Enforcement is scheduler-side, which is correct separation of concerns. Both workers trust the scheduler to respect state.

---

## 9. Protocol Versioning & Drift Risk
*Investigating: explicit version fields, implicit compatibility, silent-break risks*

### Under Investigation...

---

## Summary — Top 5 Priorities
*To be completed after investigation*

