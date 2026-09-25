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

*Investigating now...*

---

## 5. Platform Support & Operational Tooling

*Investigating now...*

---

## 6. Error Handling & Resilience Maturity

*Investigating now...*

---

## 7. Code Maintainability & Extensibility

*Investigating now...*

---

## 8. Build & Deployment (Docker Images)

*Investigating now...*

---

## 9. Decision Guide: When to Choose Which

*Synthesized after investigation...*

---

## Summary — Top 5 Priorities

*Ranking by value × effort after investigation...*
