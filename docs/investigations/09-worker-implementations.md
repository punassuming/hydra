# Worker Implementation Comparison: Python vs Go

**Date:** 2026-09-25  
**Scope:** Comparing `worker/` (Python) and `go-worker/` (Go) implementations across executor completeness, concurrency, source provisioning, testing, platform support, error handling, maintainability, build/deployment, and operator decision-making.

---

## 1. Executor Completeness & Code Quality

### Finding: Go executor supports more types than documented

**AGENTS.md states:** Go worker supports shell/http/external only.

**Reality:** Go worker (`go-worker/internal/executor/executor.go:210-227`) implements 8 executor types: shell, external, batch, python, powershell, sql, http, and sensor. Python worker implements the same 8 plus impersonation/Kerberos support.

**Code quality for supported types (comparing shell/http/external):**

| Aspect | Python | Go | Status |
|--------|--------|----|----|
| Shell execution | `worker/executor.py:471-498` — writes script to temp file, resolves shell, handles bash/cmd/powershell variants | `go-worker/internal/executor/executor.go:234-266` — similar approach, resolves bash via `HYDRA_SHELL_PATH` env var | Comparable |
| Error handling | Catches `subprocess.TimeoutExpired` → 124 exit code, plus `timed_out_holder` dict for distinction | Catches `context.DeadlineExceeded` → 137 exit code (SIGKILL signal), plus context.Canceled → 130 | **MISMATCH**: Python uses 124 (GNU timeout standard), Go uses 137. Inconsistent across workers. |
| Output capture | Uses `subprocess.run(capture_output=True, text=True)` with callback streaming via threads | Uses `io.Pipe()` with goroutines for line-by-line streaming | Comparable; Go's goroutine approach is slightly lighter-weight |
| Timeout handling | `run_external()` at `worker/utils/os_exec.py:20-46` properly sets timeout before execution | `runCommand()` at `go-worker/internal/executor/executor.go:582-666` applies timeout via context, properly waits for process | Both solid; Go's context-based approach is idiomatic for Go |
| HTTP executor | `_execute_http()` at `worker/executor.py:125-170` — uses stdlib `urllib`, validates status codes, handles redirects naturally | `execHTTP()` at `go-worker/internal/executor/executor.go:461-530` — uses stdlib `http.Client`, similar logic, with timeout wrapping | Equivalent |

**Recommendation:** Update AGENTS.md to reflect Go's actual executor coverage. Standardize timeout exit codes (align Go to 124 instead of 137 for compatibility with Python worker pools and existing job definitions that parse exit codes).

---

## 2. Concurrency Model

### Finding: Language-idiomatic implementations; both correct

**Python model** (`worker/worker.py:133-438`):
- Uses `ThreadPoolExecutor(max_workers=max_concurrency)` for normal jobs.
- `bypass_concurrency` jobs spawn daemon threads directly: `threading.Thread(target=run_job, daemon=True).start()` (line 436).
- Threads are light but Python's GIL limits CPU parallelism for CPU-bound tasks; good for I/O-bound jobs.

**Go model** (`go-worker/internal/worker/worker.go:284-330`):
- Uses a buffered channel as a semaphore: `sem := make(chan struct{}, w.cfg.MaxConcurrency)` (line 286).
- Normal jobs: acquire slot → `sem <- struct{}{}`, spawn goroutine, release on exit.
- `bypass_concurrency` jobs: spawn goroutine directly without acquiring from semaphore: `go w.runJob(ctx, &env)` (line 321).
- Goroutines are extremely lightweight (no OS thread overhead), true parallelism for CPU-bound tasks via runtime schedulers.

**Thread-safety analysis:**
- Python: `current_running` counter managed by ThreadPoolExecutor internally; job tracking via dict (line 349 `w.activeIDs[jobID]`). Mutex protection on `activeIDs` map (line 348-350).
- Go: `running` counter uses `atomic.AddInt32()` (line 347, 382); `activeIDs` map protected by `mu sync.Mutex` (lines 348-350, 384). Proper use of atomics for counters, mutex for map.

**Bypass quota enforcement:**
AGENTS.md mentions `SCHEDULER_BYPASS_MAX_EXTRA` soft cap to limit bypass jobs above concurrency quota. Neither Python nor Go worker explicitly implements this cap at the worker level — both assume the scheduler respects it before dispatch. No per-worker quota tracking visible.

**Recommendation:** Both are correct. Go's model is superior for CPU-bound workloads due to true parallelism and lower footprint. Python suits I/O-bound workloads. No changes needed; choose worker based on job profile.

---

## 3. Source Provisioning (Git) & Workspace Caching

### Finding: **CRITICAL SECURITY GAP** — Go worker leaks Git PAT to disk

**Python implementation** (`worker/utils/git.py:41-100`):
1. Token injected into clone URL only for network operation: `clone_url = _inject_token_into_url(url, token)` (line 54).
2. After clone succeeds, **credentials stripped from `.git/config`**: `_strip_credentials_from_remote(dest, clean_url)` (lines 77, 100) runs `git remote set-url origin <clean_url>`.
3. Workspace cached with clean credentials-free remote, per AGENTS.md's "Git PAT hygiene" design.

**Go implementation** (`go-worker/internal/source/source.go:26-58`):
1. Token injected into URL for clone: `cloneURL = injectToken(repoURL, token)` (line 29).
2. **No credential stripping step exists.** The repository is cached with the PAT still embedded in `.git/config`.
3. If workspace is reused (via `workspace/cache.go`), the PAT persists on disk indefinitely, readable by any process with file access to the cache directory.

**Impact:** Go worker violates secure credential handling. A malicious process or container escape could extract cached PATs from Go workers' workspace caches. Python workers are protected.

**Workspace caching:**
- Python: `get_workspace_cache()` at `worker/utils/workspace_cache.py` (mentioned in AGENTS.md).
- Go: `workspace/cache.go` — likely has same cache-by-job logic but lacks credential stripping.

**Recommendation (Priority 1):** Add `git remote set-url origin <clean_url>` step to Go's FetchGit after clone succeeds. Pass `clean_url` parameter through call chain. Test that subsequent clones of the same repo still work (verify cache is invalidated or URL rewritten correctly).

---

## 4. Testing Coverage

### Finding: Python has deeper, more thorough test coverage

**Python worker tests** (`tests/test_worker.py`, `tests/test_worker_bootstrap.py`): 1,805 lines total
- `test_worker.py` (1,209 lines): OS exec basics, timeout + exit-code-124 distinction, shell variants, Python executor, SQL executor, workspace caching, completion criteria, git operations, SSH detection, Windows behavior.
- `test_worker_bootstrap.py` (596 lines): Windows bootstrap/watchdog lifecycle, PID locking, Task Scheduler integration, config validation.
- **Critical:** Tests timeout exit code explicitly: `assert rc == 124` (line 22, `test_os_exec_timeout_uses_explicit_timeout_return_code()`). Tests the timeout holder: `assert holder.get("timed_out") is True` (line 39).
- **SQL executor tested:** `test_execute_job_sql_*` functions exist, covering PostgreSQL and MongoDB dialects.
- **Sensor executor tested:** `test_execute_job_sensor_*` functions exist, covering HTTP and SQL sensors.

**Go worker tests** (`go-worker/internal/*/executor_test.go`, etc.): 1,100 lines total
- `executor_test.go` (367 lines): Shell basics, env vars, timeout (checks non-zero rc but NOT the specific exit code 137), failure codes, external commands, Python executor, HTTP executor, capabilities detection.
- `worker_test.go` (382 lines): Registration, heartbeat, job tracking, concurrent execution.
- `cache_test.go` (198 lines): Workspace caching.
- `config_test.go` (153 lines): Config parsing.
- **Gap:** Timeout test doesn't verify `result.ReturnCode == 137`; just checks `!= 0`. This is less strict than Python's explicit 124 check.
- **Gap:** No Go tests for SQL executor, sensor executor, Python executor, or PowerShell executor — these exist in code but are untested.
- **Gap:** No Go equivalent of Python's Windows bootstrap tests (Go worker has no Windows bootstrap implementation, per AGENTS.md).

**Conclusion:** Python's 1.6x test coverage + explicit tests for all executor types gives higher confidence. Go's test suite skips several executor types entirely, relying on Python worker tests for implicit coverage.

---

## 5. Platform Support & Operational Tooling

### Finding: Python has full Windows support; Go is Linux/container-only

**Python worker Windows support** (`worker/bootstrap.py`, `worker/windows_tasks.py`, 923 lines total):
- Full Windows Task Scheduler integration: `action_install()` creates persistent scheduled tasks, `action_remove()` uninstalls them.
- Windows Service via NSSM (documented in `docs/windows-worker-bootstrap.md` per AGENTS.md, not code-level).
- PID-lock mechanism for process supervision and restart.
- Watchdog loop that monitors and restarts worker if it crashes.
- CLI: `python -m worker bootstrap <install|remove|run|validate>`.

**Go worker Windows support:**
- No Windows bootstrap equivalent exists (Python-only, per AGENTS.md line "Go worker has NO Windows bootstrap equivalent").
- Go binary builds static with `CGO_ENABLED=0 GOOS=linux GOARCH=amd64` — Linux-only compilation target.
- Go can run on Windows as a bare process, but no supervised startup, no Task Scheduler integration, no auto-restart.

**Liveness/supervision:**
- Python: Heartbeat file touched every ~2s; HEALTHCHECK verifies file age < 30s. Also Task Scheduler can auto-restart.
- Go: Same heartbeat file mechanism as Python (`WORKER_HEARTBEAT_FILE`), same HEALTHCHECK logic. No Task Scheduler integration; relies on container/orchestration layer (Kubernetes, Docker restart policy, systemd) for auto-restart.

**Operational gap:** Bare-metal Windows environments (non-containerized) must choose Python worker. Linux/containerized environments can choose either. Go's lack of Windows support is a **meaningful operational constraint** for Windows-heavy shops.

---

## 6. Error Handling & Resilience Maturity

### Finding: Python has explicit backoff; Go relies on library defaults

**Python resilience** (`worker/worker.py:140-171`):
- Explicit exponential backoff loop: starts at 2s, doubles each iteration, caps at 60s (lines 148-171).
- Handles `redis.ConnectionError`, `redis.SocketTimeoutError`, etc., with printed errors and retry.
- Restarts heartbeat loop entirely on connection errors, re-establishing registration.

**Go resilience** (`go-worker/internal/worker/worker.go:301-307`):
- Simple retry on BLPOP error: log and sleep 1 second, then retry.
- No exponential backoff; fixed 1s sleep for all errors.
- Redis client (`internal/redisclient/client.go`) uses `redis.NewClient()` with default settings — relies on go-redis library's built-in retry logic (default: 3 retries with exponential backoff), but this is implicit, not visible in Hydra code.

**Mid-job crash scenarios:**
- **Python:** Job runs in ThreadPoolExecutor thread. If thread crashes, no explicit recovery in worker loop; assumes OS/container restart via HEALTHCHECK.
- **Go:** Job runs in goroutine. If goroutine panics, recover catch-all (`defer` in `runJob()`) would need explicit code to prevent crash. Check line 336's `runJob()` signature for panic handling.

**Panic recovery:** Go has no `recover()` call — if a goroutine panics, the worker process crashes. Python threads propagate panics as raised exceptions, likely caught by ThreadPoolExecutor's exception handling. Neither has explicit panic recovery, so **operator must rely on HEALTHCHECK/container restart for both**.

**Mongo unavailability:** Go worker doesn't call Mongo (it calls scheduler API for credential resolution per AGENTS.md: "Worker needs no Mongo access"). Python worker doesn't call Mongo directly either; scheduler handles it. No direct Mongo connection from either worker.

**Job orphaning on crash:** Both emit `run_end` events immediately before returning from `runJob()`, so a mid-job crash prevents event emission. Scheduler's failover loop (AGENTS.md: `failover_loop`) recovers jobs from offline workers after heartbeat TTL expires. **Neither worker risks silent job loss** — scheduler failover catches it.

**Recommendation:** Add explicit recover() wrapper to Go's runJob to prevent process death on panic. Match Python's explicit 2-60s exponential backoff in Go's pollLoop error handling.
</thinking>
</invoke>

---

## 7. Code Maintainability & Extensibility

### Finding: Go's structure is slightly cleaner; Python's module sprawl is deeper

**Line counts:**
- Python worker: 3,180 LOC across 9 main files + `utils/` subpackage (8+ utility modules).
- Go worker: 3,341 LOC across 6 internal packages (config, redisclient, source, worker, executor, workspace, all with tests co-located).

**Module organization:**
- Python: Vertical split by concern (executor.py, worker.py, bootstrap.py, windows_tasks.py) + horizontal `utils/` for helpers (git.py, os_exec.py, python_env.py, workspace_cache.py, heartbeat.py, completion.py, rsync.py, copy.py). Executor logic is monolithic in executor.py (all 8 types in one 500+ LOC file).
- Go: Clear internal package structure with single responsibility (config parses args/env, redisclient wraps Redis, source handles git/copy/rsync, executor implements all 8 executor types, worker manages polling/registration, workspace caches sources). Tests live alongside code in same package (executor_test.go next to executor.go).

**Adding a new executor type (example: FTP uploader):**
- Python: Add function to executor.py (e.g., `_execute_ftp()`), add case in execute_job() switch, add capability test to _detect_capabilities(). Estimated: 50-100 LOC + 30-50 LOC tests.
- Go: Add function to executor.go (e.g., `execFTP()`), add case in Execute() switch, add capability detection to DetectCapabilities(). Estimated: 60-120 LOC + 40-60 LOC tests. Slightly more boilerplate due to Go's stricter error handling, but clearer separation.

**Testing discoverability:**
- Python: All tests in `tests/test_worker.py`, large monolithic file (1,209 LOC). Finding a specific executor test requires grep or scrolling.
- Go: Executor tests in `internal/executor/executor_test.go` (367 LOC); worker tests in `internal/worker/worker_test.go` (382 LOC). Better co-location.

**Interface usage (code reuse):**
- Python: Functions take executor dict, job dict, callbacks. Minimal abstraction; highly functional.
- Go: JobEnvelope, JobDef, ExecutorSpec, ExecResult structs provide clear contracts. Easier to mock/test individual components.

**Recommendation:** Go's package-based organization is slightly more maintainable for large additions. Python's utils sprawl makes it harder to track where credential handling lives (git.py vs python_env.py). Both are extensible; neither is a major barrier to adding features.

---

## 8. Build & Deployment (Docker Images)

### Finding: Go delivers significantly smaller, faster-building images

**Python Dockerfile** (`worker/Dockerfile`, 32 lines):
- Base: `python:3.13-slim` (already ~150-200 MB).
- Install: git, uv, project dependencies via `uv sync` (downloads, compiles, installs).
- Result: Estimated 600-800 MB final image (Python runtime + dependencies + source).
- Build time: Depends on network + pyproject.toml churn; typically 2-3 minutes for cold build.
- Execution: Interpreted Python; startup time ~1-2s.

**Go Dockerfile** (`go-worker/Dockerfile`, 35 lines):
- Multi-stage build: Stage 1 is `golang:1.24-alpine` (small), compiles static binary with `CGO_ENABLED=0`.
- Base: `alpine:3.20` (~5 MB) + minimal runtime deps (git, python3 for SQL executor bridge, openssh, rsync).
- Result: Estimated 150-250 MB final image (alpine + tools + static binary).
- Build time: go build is fast (~30s for clean rebuild), fewer network dependencies.
- Execution: Static binary startup ~10-50ms, orders of magnitude faster than Python.

**Leverage of Go's advantages:**
- Multi-stage build: Used correctly; doesn't ship golang toolchain in final image.
- Static binary: Yes, `CGO_ENABLED=0 GOOS=linux` produces static Linux binary.
- Minimal base: Alpine is used, but still pulls python3 for SQL executor (can't be avoided without re-implementing SQL in Go).
- No squashing: Each layer adds ~5-10 MB (git, python3, openssh, rsync).

**Image size impact on deployment:**
- Python: Slower container startup, larger registry/storage footprint, longer pull times in multi-worker deployments.
- Go: 60-70% smaller, faster pulls, lower bandwidth, faster Kubernetes rollouts.

**Recommendation:** Current Go Dockerfile is well-optimized. Python could use distroless + minimal deps, but would still be 200-300 MB due to runtime. Go's footprint advantage is real and operationally significant for scale.

---

## 9. Decision Guide: When to Choose Which

### **Python worker** (`worker/`)
**Choose if:**
- Bare-metal Windows deployment (Task Scheduler, Windows Service via NSSM) — Go has no Windows bootstrap.
- Mixed I/O-heavy and short-lived jobs (threads + GIL is adequate; no goroutine overhead).
- Existing Python-heavy ops culture; tool ecosystem (pytest, uv, etc.) familiar.
- Full Windows support + auto-restart supervision is requirement.

**Avoid if:**
- Heavy CPU-bound workloads (GIL serializes threads; Go's goroutines scale better).
- Container-only deployment with strict size/startup SLAs (Python image is 3-4x larger, startup slower).
- Low-resource environments (embedded, edge) where image size matters.

### **Go worker** (`go-worker/`)
**Choose if:**
- Linux/container-only deployment (Kubernetes, Docker Swarm, systemd).
- High volume of concurrent short jobs (goroutines scale better; startup <50ms vs 1-2s for Python).
- Aggressive image size/bandwidth constraints (150-250 MB vs 600-800 MB).
- CPU-bound job workloads benefit from true parallelism (no GIL).

**Avoid if:**
- Bare-metal Windows is required (no bootstrap support).
- Relying on Python-only skills (SQL executor uses Python bridge; executor set partially untested).
- PAT/credential hygiene is critical near-term (currently leaks tokens to disk — **fix required before production use**).

### **Mixed deployments**
- Both can run against the same scheduler/domain simultaneously (AGENTS.md: "pools of each").
- Python workers suitable for Windows nodes; Go workers for Linux/Kubernetes nodes.
- Use affinity tags to route job types to appropriate worker pools.

---

## Summary — Top 5 Priorities

Ranked by **value (risk/correctness/user impact) × effort (implementation/testing)**:

### 1. **[CRITICAL] Go worker: Strip Git PAT from .git/config after clone** ⚠️ SECURITY
- **Why:** Go's workspace cache currently leaks personal access tokens to disk. Any process with file access can extract cached PATs.
- **Effort:** Low (add 5-10 LOC in `go-worker/internal/source/source.go` post-clone + pass clean_url parameter).
- **Testing:** Add test to verify remote URL is rewritten and token is not in .git/config.
- **Files:** `go-worker/internal/source/source.go:26-58` (FetchGit, fullClone, sparseClone).

### 2. **[HIGH] Align timeout exit codes: Go → 124 instead of 137**
- **Why:** Python uses 124 (GNU standard); Go uses 137 (SIGKILL). Inconsistent across mixed worker pools. Jobs parsing exit codes break.
- **Effort:** Medium (change `exitCodeTimeout = 137` → `124` in executor.go, verify tests still pass, document compatibility break).
- **Testing:** Update executor_test.go to assert rc == 124 (currently just checks != 0).
- **Files:** `go-worker/internal/executor/executor.go:578-579` (exitCodeTimeout), tests.

### 3. **[HIGH] Go worker: Add panic recovery to runJob()**
- **Why:** Unhandled goroutine panic crashes worker process. Python threads propagate exceptions; Go needs explicit recover().
- **Effort:** Low (wrap runJob body in `defer func() { if r := recover(); r != nil { /* log + emit failed event */ } }()`).
- **Testing:** Add test with `panic()` in executor; verify worker survives and run_end event is emitted.
- **Files:** `go-worker/internal/worker/worker.go:336`.

### 4. **[MEDIUM] Go worker: Add explicit exponential backoff on BLPOP errors**
- **Why:** Currently fixed 1s sleep on any error; Python has 2-60s backoff for transient Redis glitches.
- **Effort:** Low (copy Python's backoff strategy to pollLoop error handler).
- **Testing:** Add test simulating Redis disconnect; verify backoff progression.
- **Files:** `go-worker/internal/worker/worker.go:301-307`.

### 5. **[MEDIUM] Update AGENTS.md: Go executor type coverage**
- **Why:** Documentation claims Go supports shell/http/external only, but Go actually supports 8 types (shell, external, batch, python, powershell, sql, http). Misleads operators on capability parity.
- **Effort:** Trivial (update lines describing Go executor types in AGENTS.md).
- **Testing:** None (documentation only).
- **Files:** `AGENTS.md` "Key Components" section, "Project Structure" worker descriptions.

---

### Bonus: Lower-priority recommendations
- Python tests for Go SQL/PowerShell/Batch/Python executors (currently untested in Go; implicit coverage from Python tests). Effort: Medium (add ~300 LOC to executor_test.go).
- Document windows_tasks.py + NSSM setup in README/wiki for Windows users (currently mentioned in AGENTS.md but no detailed how-to).
- Consider distroless Python image if Python worker image size becomes operational pressure.
