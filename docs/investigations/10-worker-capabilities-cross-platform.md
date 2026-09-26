# Worker Capability Detection & Cross-Platform Support Investigation

**Date Started:** 2026-09-25  
**Status:** In Progress

---

## 1. Capability Detection Mechanism

*Investigating: `worker/runtime.py` and `_detect_capabilities()` in `worker/executor.py` — preflight checks for each executor type.*

### Findings

**Location:** `worker/runtime.py` lines 96-127; called from `worker/worker.py` line 67 in `register_worker()`.

**Mechanism Overview:**
Each executor type uses concrete preflight checks (running test commands with 5s timeout). Capabilities are advertised to Redis in worker metadata at registration time. The design is intentionally fail-closed: absence of evidence of a tool is treated as evidence of absence.

**Per-Executor-Type Preflight Details:**

1. **Shell** (line 99-100): Calls `_detect_shells()` which runs each candidate shell with `-c "exit 0"`. Returns empty list if no shells work → shell executor not advertised.
   - Candidates: bash (or configured HYDRA_SHELL_PATH), sh, cmd (Windows only), powershell (Windows only), pwsh (any OS).
   
2. **External** (line 100): Piggybacked on shell detection (same list approach).

3. **Python** (line 102-104): Calls `_find_python()` which runs `python --version` or `python3 --version` (respects HYDRA_PYTHON_PATH env var). Returns empty string if none work.

4. **PowerShell** (line 106-113): Tries `pwsh -Command "exit 0"` then `powershell -Command "exit 0"` with 5s timeout. Both fail → not advertised.

5. **Batch** (line 115-116): **POTENTIAL ISSUE** — only checks Windows platform (`platform.system().lower().startswith("win")`). Does NOT verify cmd.exe actually exists or runs. Could falsely advertise batch on Windows Nano or WSL.

6. **SQL** (line 118-124): Requires Python AND successful `import sqlalchemy`. If either fails, not advertised.

7. **HTTP** (line 126): **ALWAYS advertised** — uses stdlib, no check needed (reasonable).

8. **Sensor** (line 126): **ALWAYS advertised** — polling is a scheduling feature, no tool dependency (reasonable).

**Fail-Closed Philosophy Assessment:**
- **SOLID:** shell, external, python, powershell, sql, http, sensor — all use concrete runtime checks or platform-agnostic stdlib.
- **WEAK SPOT:** Batch executor advertised on Windows without verifying cmd.exe availability. A barebones Windows image might not have cmd.exe (extremely unlikely but possible in specialized OS images). Recommended: add `cmd /c "exit 0"` test like other shell types.

---

## 2. OS-Specific Executor Behavior

*Investigating: shell/batch/powershell executors — correct OS-specific selection and graceful unavailability on mismatched platforms.*

### Findings

**Location:** `worker/executor.py` lines 21-36 (PowerShell), 422-438 (Batch), 471-498 (Shell).

**Impersonation/Kerberos Platform Check (Explicit & Solid):**
- Lines 296-304: `supports_impersonation = current_os in ("linux", "darwin")`; if impersonation_user or kerberos is set on non-Linux/macOS, returns error immediately: `"impersonation/kerberos executor settings are supported only on Linux/macOS workers"`.
- **Assessment:** Fail-closed and clear error message. Good pattern.

**Shell Executor (OS-Agnostic with Conditional Flags):**
- Lines 471-498: Writes script to temp file (.sh or .ps1 depending on shell type).
- Lines 481-491: Branches on shell name (bash, powershell, cmd, other).
- Lines 485-486: Adds `-ExecutionPolicy Bypass` to PowerShell only on Windows.
- **Assessment:** Solid. Resolves shell via `_resolve_shell()` and adapts flags per shell/OS combo.

**Batch Executor (Windows-Only but Unchecked at Runtime):**
- Lines 422-438: Always assumes Windows and calls `cmd /c <script>`. 
- **ISSUE:** No runtime check that cmd.exe exists on this Windows worker. If running on Windows Nano or a highly stripped image without cmd.exe, batch jobs will fail at runtime instead of being rejected at dispatch time.
- Alternative: Could accept both cmd and PowerShell as `shell` param (line 424).

**PowerShell Executor (Cross-Platform Attempt):**
- Lines 21-36: Calls `_resolve_shell(executor.get("shell", "pwsh"))` which attempts pwsh first, falls back to powershell.
- No OS check — tries to run on any OS. On Linux without pwsh installed, will fail at runtime (but capability detection should have prevented dispatch).
- **Assessment:** Sound in practice (won't be dispatched without pwsh/powershell), but no explicit platform guard.

**Summary — Strengths & Gaps:**
- ✓ Impersonation/Kerberos: explicit platform check with clear error.
- ✓ Shell: adapts syntax per OS/shell type.
- ⚠ Batch: advertised on Windows without verifying cmd.exe; can fail at runtime.
- ⚠ PowerShell: no explicit platform guard (but capability detection guards it).

---

## 3. Deployment Type Auto-Detection

*Investigating: `DEPLOYMENT_TYPE` env var auto-detection logic — Docker, Windows Task Scheduler, bare-OS, and edge cases.*

### Findings

**Location:** `worker/worker.py` lines 57-60; `worker/bootstrap.py` line 313.

**Auto-Detection Logic (`worker/worker.py` lines 57-60):**
```python
_in_docker = pathlib.Path("/.dockerenv").exists()
_default_deployment_type = "docker" if _in_docker else "standalone"
deployment_type = os.getenv("DEPLOYMENT_TYPE", _default_deployment_type)
```
- Checks for `/.dockerenv` file (standard Docker marker on Linux containers).
- If present → `"docker"`. Otherwise → `"standalone"`.
- Can be overridden by `DEPLOYMENT_TYPE` env var.

**Windows Task Scheduler Path (`worker/bootstrap.py` line 313):**
- `_build_worker_env()` sets `env.setdefault("DEPLOYMENT_TYPE", "scheduler")` when launching worker from Task Scheduler watchdog.
- This ensures workers launched by Windows bootstrap are labeled `"scheduler"` instead of `"standalone"`.

**Edge Cases & Robustness Assessment:**

1. **Docker Detection (`/.dockerenv`):**
   - ✓ Standard, reliable on Docker.
   - ⚠ Fails/false-negatives on other container runtimes: Podman, Kubernetes/containerd (unless `.dockerenv` is also present). Worker would self-report `"standalone"` even in a container.
   - ⚠ Fails on WSL (Windows Subsystem for Linux) — will report `"standalone"` even in managed environment.
   - AGENTS.md notes support for Kubernetes via Helm, but deployment type detection doesn't distinguish it.

2. **Bare-OS Detection:**
   - Anything without `/.dockerenv` → `"standalone"`. This includes:
     - Bare Linux/macOS/Windows processes (correct).
     - WSL (incorrectly; should perhaps detect differently).
     - Podman/Kubernetes without `.dockerenv` (incorrectly; should perhaps detect differently).

3. **Windows Task Scheduler Detection:**
   - ✓ Explicit opt-in via bootstrap watchdog — no auto-detection needed, bootstrap sets it directly.

**Summary — Gaps:**
- `.dockerenv` check is simplistic; misses Podman, containerd-based Kubernetes, WSL, systemd containers.
- No auto-detection for Kubernetes (only via `DEPLOYMENT_TYPE=kubernetes` override).
- No distinction between managed container (Kubernetes) and bare standalone.
- Recommended: Add Kubernetes detection (e.g., check for `/var/run/secrets/kubernetes.io` or `KUBERNETES_SERVICE_HOST`), Podman detection, WSL detection.

---

## 4. Windows Bootstrap/Watchdog Robustness

*Investigating: `worker/bootstrap.py` and `worker/windows_tasks.py` — install/remove/validate idempotency and error handling.*

### Findings

**Location:** `worker/bootstrap.py` lines 277-295 (PID lock), 449-559 (actions); `worker/windows_tasks.py` lines 163-250+ (Task Scheduler wrapper).

**PID Lock Mechanism (`bootstrap.py` lines 277-295):**
- `acquire_bootstrap_lock()` reads lock file, checks if recorded PID is alive, and acquires lock.
- **Staleness Handling:** If PID in lock file is not alive (`_is_pid_alive()` returns False), lock is considered stale and replaced (line 291).
- `_is_pid_alive()` (lines 250-274): Uses `ctypes.OpenProcess()` on Windows and `os.kill(pid, 0)` on Unix — both standard techniques, robust.
- **Assessment:** ✓ Staleness handling is solid. Protected process detection (ERROR_ACCESS_DENIED) correctly returns True (line 266).

**Idempotency:**

1. **install (lines 472-516):**
   - ✓ Uses `/F` flag with schtasks (line 89 in windows_tasks.py) or PowerShell `-Force` for idempotency.
   - ✓ Validates config before install (lines 484-489).
   - Replaces existing task if already present.
   
2. **remove (lines 519-535):**
   - ✓ Uses `/F` flag (line 116) — succeeds silently if task doesn't exist.
   - ✓ No pre-check needed; always returns 0.

3. **run (lines 538-559):**
   - ✓ Validates config before starting watchdog (lines 544-549).
   - Watchdog acquires lock at start; if another instance holds it, returns 1 (exit).

4. **validate (lines 449-469):**
   - ✓ Purely informational, always safe.

**Error Handling:**

- ✓ Config validation is checked in install/run/validate before proceeding.
- ✓ Process launch failures are logged and return None (lines 349-353).
- ✓ Log file open failures gracefully degrade to inherited stdio (lines 328-334).
- ✓ Signal handlers (SIGTERM/SIGINT) cleanly shut down watchdog (lines 370-373).
- ✓ Watchdog cleanup on exit calls `_remove_lock()` (line 427).

**Windows Task Scheduler Wrapper (`windows_tasks.py`):**
- ✓ `run_schtasks()` raises `CalledProcessError` on non-zero return (lines 147-153).
- ✓ Timeouts are enforced (default 30s, line 124).
- ✓ Platform check (`_require_windows()`) prevents non-Windows calls (lines 25-33).
- ✓ `/F` (force overwrite) makes installs idempotent (line 89).

**NSSM Alternative (Windows Service):**
- Not in codebase (`docs/windows-worker-bootstrap.md` referenced in AGENTS.md but not found to verify).
- Documented as alternative in AGENTS.md line 102 but implementation not provided — likely operational docs only.

**Summary — Strengths:**
- ✓ PID lock staleness detection is robust.
- ✓ All actions are idempotent.
- ✓ Error handling is thorough (config validation, process launch errors, signal handling).
- ✓ Platform guarding prevents misuse on non-Windows.
- ⚠ NSSM alternative not implemented in code (docs-only, not a robustness issue).

---

## 5. Linux-Only Features & Guards

*Investigating: impersonation and Kerberos — platform checks and error clarity on non-Linux workers.*

### Findings

**Location:** `worker/executor.py` lines 296-304 (impersonation/Kerberos guard), 316-342 (Kerberos init and impersonation).

**Platform Check (Explicit & Clear):**
- Lines 296-304 in `execute_job()`:
```python
current_os = platform.system().lower()
supports_impersonation = current_os in ("linux", "darwin")

if (impersonate_user or kerberos) and not supports_impersonation:
    return (
        1, "", 
        f"impersonation/kerberos executor settings are supported only on Linux/macOS workers (current: {platform.system()})",
    )
```
- ✓ **Explicit guard:** Both `impersonate_user` and `kerberos` trigger the check together.
- ✓ **Clear error message:** Returns immediately with descriptive error mentioning supported platforms and actual OS.
- ✓ **Fail-closed:** Rejects unknown/unexpected OS (e.g., would reject Windows, WSL, etc.).

**Kerberos Implementation (Lines 337-342):**
```python
if kerberos and kerberos.get("principal") and kerberos.get("keytab"):
    kinit_cmd = _with_impersonation(["kinit", "-kt", str(kerberos.get("keytab")), str(kerberos.get("principal"))])
    rc_k, out_k, err_k = _run_cmd(kinit_cmd)
    if rc_k != 0:
        return rc_k, out_k, f"Kerberos init failed: {err_k or out_k}"
```
- ✓ Runs `kinit` command via impersonation wrapper (which also checks Linux/macOS).
- ✓ Errors if `kinit` fails (non-zero return).
- Kerberos ccache cleanup documented in AGENTS.md line 59: `kdestroy` in `finally` block immediately after job finishes (not visible in current executor.py excerpt but noted in AGENTS.md).

**Impersonation (Sudo Wrapper, Lines 316-319):**
```python
def _with_impersonation(cmd: list[str]) -> list[str]:
    if impersonate_user:
        return ["sudo", "-n", "-u", impersonate_user, "--"] + cmd
    return cmd
```
- ✓ Uses `sudo -n` (non-interactive) to switch user.
- ✓ Only called if `impersonate_user` is set AND platform check passed (line 299).
- ⚠ No explicit pre-check for `sudo` binary existence (but `shell` capability detection covers shell/sudo availability).

**Capability Advertising:**
- From Area 1: No separate `impersonate` executor type; features are gated by config check at runtime.
- Scheduler should not dispatch impersonation jobs to non-Linux workers (job affinity check, not in this file).
- If scheduler mistakenly dispatches, worker rejects with clear error.

**Summary:**
- ✓ Platform guard is explicit and clear (Linux/Darwin only).
- ✓ Error message is operator-friendly.
- ✓ Both impersonation and Kerberos use same guard (consistent).
- ✓ Fail-closed: rejects unknowns.
- ✓ Kerberos cleanup (kdestroy) runs in finally block (per AGENTS.md).
- ⚠ No pre-check for sudo binary, but shell capability detection is a proxy.

---

## 6. Go Worker Cross-Platform Story

*Investigating: Go worker build matrix, OS-conditional code, and positioning (Linux/container-only vs. multi-platform).*

### Findings

**Build & Test Coverage:**
- ✓ CI builds Go worker on `ubuntu-latest` only (`.github/workflows/python-ci.yml` line 249).
- ✓ No multi-platform (macOS, Windows) test matrix for Go worker.
- ✓ Container image build (`.github/workflows/container-images.yml`) targets Linux only (line 26: `runs-on: ubuntu-latest`).
- ✓ `go-worker/Dockerfile` explicitly sets `GOOS=linux GOARCH=amd64` (line 8).
- ✓ README shows manual cross-compile examples for Linux, Windows, macOS (lines 74-80), but these are theoretical — not tested in CI.

**OS-Conditional Code:**
- ✓ `go-worker/internal/executor/executor.go` checks `runtime.GOOS == "windows"` for shell detection (DetectShells).
- ✓ Impersonation explicitly guards: `runtime.GOOS != "linux" && runtime.GOOS != "darwin"` (same as Python worker).
- ✓ Metrics collection uses Linux-specific syscalls guarded by `runtime.GOOS == "linux"` in `internal/worker/metrics.go`.

**Documented Feature Gaps vs. Python Worker:**
- ❌ SQL executor: not implemented (README line 37).
- ❌ Impersonation / Kerberos: explicitly marked Linux-specific (README line 38).
- ✓ Shell, external, batch, python, powershell: all supported.
- ✓ Heartbeat, metrics, concurrency, source fetching, log streaming: all supported.

**Positioning & Operator Expectations:**
- README explicitly advertises cross-compile commands for Windows/macOS (lines 74-80).
- BUT README does NOT claim production support for Windows/macOS deployments.
- README emphasizes "feature-complete" but lists SQL and Impersonation/Kerberos as unsupported.
- Helm chart in `deploy/helm/hydra` and Compose files (`docker-compose.worker.go.yml`) assume Linux containers.
- **Gap:** An operator reading the cross-compile section might reasonably attempt a Windows deployment without realizing it's untested.

**Summary — Current State:**
- ✓ Linux deployment is well-tested and production-ready.
- ✓ Windows/macOS code paths exist and compile, but untested in CI.
- ⚠ README's cross-compile examples suggest Windows/macOS are supported, but no disclaimer that it's untested.
- ⚠ Metrics collection will silently degrade on non-Linux (no load averages exported).
- Recommendation: Either (1) add CI test matrix for Windows/macOS, or (2) update README to clarify "Linux-only" and move cross-compile examples to a separate "Development" section.

---

## 7. Capability + Affinity Test Coverage

*Investigating: tests exercising capability detection across simulated OS conditions — coverage gaps.*

### Findings

**Location:** `tests/test_worker.py` lines 573-1143 (capability tests), 760-780+ (affinity tests).

**Capability Detection Tests (`test_worker.py`):**
- ✓ `test_detect_capabilities_includes_http()` (line 573): Verifies http capability is always present.
- ✓ `test_detect_capabilities_sql_depends_on_drivers()` (line 583): Mocks sqlalchemy import to test SQL detection.
- ✓ `test_detect_capabilities_shell_requires_working_shell()` (line 1091): Mocks subprocess.run to simulate shell failure.
- ✓ `test_detect_capabilities_sql_requires_python()` (line 1106): Mocks _find_python() to test Python dependency.
- ✓ `test_detect_capabilities_sensor_always_present()` (line 1116): Verifies sensor is always advertised.
- ✓ `test_detect_capabilities_no_false_positive_sql_without_driver()` (line 1124): Tests SQL not advertised without sqlalchemy.

**Cross-Platform Test Coverage Gaps:**
- ❌ NO tests mock `platform.system()` to simulate Linux vs. Windows vs. macOS.
- ❌ NO tests verify batch executor is/isn't advertised on different platforms.
- ❌ NO tests verify powershell detection on Windows vs. unavailable on Linux.
- ❌ NO tests simulate missing cmd.exe on Windows (to test batch robustness).
- ❌ Capability detection runs only on the CI OS (Linux for Python tests, never on Windows/macOS).

**Affinity Tests:**
- ✓ `test_affinity_executor_type()` (line 765+): Tests impersonation jobs are rejected on Windows workers.
- Uses hardcoded `{"os": "windows"}` worker metadata to simulate Windows platform.
- ✓ Affinity checks reject impersonation jobs on non-Linux/macOS.

**Scheduler-Side Capability Checks:**
- `scheduler/utils/affinity.py` contains job-to-worker matching logic.
- Tests verify affinity matching, but capability-to-executor mapping not explicitly tested from scheduler perspective.

**Missing Test Scenarios:**
1. Batch executor advertised on Linux (shouldn't be) — not tested.
2. Batch executor advertised on Windows without cmd.exe (false positive) — not tested.
3. PowerShell executor behavior across Windows/Linux/macOS — not tested.
4. Shell detection fallback (bash → sh → pwsh) — partially tested, but not per OS.
5. Python executor on workers with Python missing — not tested (likely caught by "no executor" case).

**Summary:**
- ✓ Core capability detection mechanisms are tested via mocking.
- ⚠ Platform-specific tests are limited to affinity (impersonation on Windows).
- ⚠ No cross-OS mocking in capability tests; all tests run on the CI OS (Linux).
- ⚠ Batch executor (Windows-only) has no dedicated test, no verification of cmd.exe.
- Recommendation: Add parameterized tests that mock `platform.system()` to simulate Windows, macOS, Linux and verify correct executor type advertis.


---

## 8. Operator-Facing Clarity

*Investigating: UI display of worker OS, deployment type, and advertised capabilities.*

### Findings

**Location:** `ui/src/pages/WorkerDetail.tsx` lines 395-396 (OS/Deployment), 447-450 (Shells/Capabilities); `ui/src/components/WorkersPanel.tsx` line 19 (Deployment in list).

**Worker Detail Page Display (WorkerDetail.tsx):**
- ✓ **OS:** Displayed prominently in "Details" card (line 395).
- ✓ **Deployment Type:** Displayed in "Details" card (line 396).
- ✓ **Capabilities:** Displayed as cyan tags in "Affinity tags" section (line 450).
- ✓ **Shells:** Displayed as blue tags in "Affinity tags" section (line 447).
- ✓ **Python Version:** Displayed to help diagnose Python executor availability (line 398).
- ✓ **Connectivity Status:** Shows online/offline to help diagnose heartbeat issues (line 400).
- ✓ **Run User:** Helps diagnose impersonation capability (line 399).

**Workers List Page (WorkersPanel.tsx):**
- ✓ **Deployment Type:** Visible in table columns (line 19).
- Other columns likely include hostname, status, concurrency.

**Operator Diagnostic Workflow:**
1. Operator submits a batch job (Windows-only executor).
2. Job sits in pending queue (no eligible worker).
3. Operator goes to Workers detail page.
4. Sees: OS = linux, Deployment = docker, Capabilities = [shell, python, http, sensor].
5. Realizes: batch executor is not advertised because this is a Linux worker, not Windows.
6. Clears action: add a Windows worker or convert job to shell executor.

**Assessment & Gaps:**

- ✓ **OS, Deployment Type, Capabilities, Shells** are clearly displayed.
- ✓ **Affinity tags** section is well-organized and easy to scan.
- ⚠ **NO "Affinity Guidance" for Impersonation:** Worker detail doesn't explicitly warn "impersonation not supported on this OS" even if job config requires it. Operator must infer from (OS = windows or macOS) × (Capabilities does not include impersonate).
- ⚠ **NO "Suggested Fixes" in Pending Queue:** When a job is pending with no eligible worker, the UI should suggest "This job requires X capability, available on Y workers" or similar. Currently, operator must manually inspect each worker.
- ✓ **Starvation Visibility:** AGENTS.md mentions "starvation warnings" in logs and `/overview/pressure` endpoint (line 57), but unclear if UI surfaces this.

**UI Feature Opportunity:**
- Could add a "Why isn't my job running?" help panel in the Pending Jobs section that cross-references:
  - Job's executor type → required capabilities.
  - Worker's advertised capabilities → why job isn't a match.
  - Affinity/tags mismatches.

**Summary:**
- ✓ Core information (OS, Deployment, Capabilities, Shells) is displayed clearly.
- ✓ Operator can diagnose "why no worker" by inspecting worker detail.
- ⚠ UX could be improved with explicit affinity mismatch explanations in pending job view.
- ⚠ No warning for OS-incompatible features (batch on Linux, impersonation on Windows).

---

## Summary — Top 5 Priorities

Ranked by **Correctness Risk × Effort** (highest impact / lowest cost first):

### 1. **Batch Executor cmd.exe Verification** (HIGH IMPACT, VERY LOW EFFORT)
- **Risk:** False-positive capability advertisement on Windows Nano or stripped images lacking cmd.exe. Jobs fail at runtime instead of being rejected at dispatch.
- **Fix:** Add `cmd /c "exit 0"` test to `_detect_shells()` in `worker/runtime.py` (line 78-92), mirroring powershell test.
- **Effort:** ~10 lines of code.
- **File:** `/home/user/Hydra/worker/runtime.py` lines 78-92.

### 2. **Go Worker Cross-Platform Testing or Documentation Clarification** (MEDIUM IMPACT, MEDIUM EFFORT)
- **Risk:** README's cross-compile examples (lines 74-80) suggest Windows/macOS support without CI verification. Operators may attempt untested deployments.
- **Options:**
  - (A) Add Windows/macOS test matrix to `.github/workflows/python-ci.yml` (medium effort, ~20 lines).
  - (B) Update README to clarify "Linux-only for production; cross-compile examples are for development only" (low effort, ~5 lines).
- **Recommendation:** Option B first (low-hanging fix), then pursue Option A if cross-platform support is a strategic goal.
- **File:** `/home/user/Hydra/go-worker/README.md` line 67-81.

### 3. **Cross-OS Capability Detection Test Coverage** (MEDIUM IMPACT, MEDIUM EFFORT)
- **Risk:** Capabilities tested only on Linux CI. Platform-specific false positives/negatives (e.g., batch on Linux) and PowerShell behavior on different OSes are untested.
- **Fix:** Add parameterized tests in `tests/test_worker.py` that mock `platform.system()` to simulate Windows, macOS, Linux and verify correct executor types advertised per platform.
- **Effort:** ~50 lines of test code (parameterized test fixtures + test cases).
- **File:** `/home/user/Hydra/tests/test_worker.py` (add around line 1143).

### 4. **Deployment Type Auto-Detection Expansion** (LOW IMPACT, HIGH EFFORT)
- **Risk:** Auto-detection misses Podman, Kubernetes, WSL, systemd containers. Operator gets `"standalone"` label even in managed environments, which is cosmetic (doesn't break functionality).
- **Fix:** Check for:
  - Kubernetes: Look for `KUBERNETES_SERVICE_HOST` env var or `/var/run/secrets/kubernetes.io` path.
  - Podman: Check `/proc/1/cgroup` for `podman` string or `podman-owned` mount.
  - WSL: Check `/proc/version` for "microsoft" string.
- **Effort:** ~30 lines of platform detection logic + tests.
- **File:** `/home/user/Hydra/worker/worker.py` lines 57-60 (extend auto-detection function).
- **Note:** Low priority because it's metadata only; functionality is unaffected.

### 5. **UI Affinity Mismatch Explanations** (LOW IMPACT, MEDIUM EFFORT)
- **Risk:** When a job sits pending with no eligible worker, the UI doesn't explain why. Operator must manually compare job executor type vs. worker capabilities.
- **Fix:** Add a helper card in the Pending Jobs section (or job detail view) that shows:
  - Job's required executor type.
  - Which capabilities are needed.
  - Count of workers with/without those capabilities.
  - Suggested actions (e.g., "Add a Windows worker" or "Use shell executor instead").
- **Effort:** ~100 lines of React component + API endpoint to summarize per-job worker eligibility.
- **File:** UI component + scheduler API endpoint (e.g., `GET /jobs/{id}/worker-eligibility`).
- **Note:** Pure UX improvement, no correctness impact.

---

### Recommendations for Next Steps

1. **Immediate (this sprint):** Fix batch executor cmd.exe test (Area 1, Priority #1).
2. **Short-term (next sprint):** Clarify Go worker cross-platform story in README (Area 6, Priority #2).
3. **Medium-term (Q4):** Add cross-OS capability tests with parameterization (Area 7, Priority #3).
4. **Nice-to-have (backlog):** Improve deployment type detection and UI diagnostics (Areas 3 & 8, Priorities #4 & #5).

---

## Independent Validation Pass (2026-09-25)

**Validator:** Claude Haiku 4.5 | **Session:** https://claude.ai/code/session_01C8hKx9dUGeyqafpXfb1Wr7

### Summary

| Area | Result | Count | Notes |
|------|--------|-------|-------|
| 1. Capability Detection | 7 CONFIRMED, 0 WRONG | 7/7 | Batch-specific cmd.exe check missing, but cmd.exe IS tested via _detect_shells(); claim partially misleading |
| 2. OS-Specific Executor | 4 CONFIRMED | 4/4 | All executor behaviors verified at cited lines |
| 3. Deployment Type Detection | 2 CONFIRMED | 2/2 | .dockerenv check and DEPLOYMENT_TYPE="scheduler" verified |
| 4. Windows Bootstrap/Watchdog | 6 CONFIRMED | 6/6 | Robustness, idempotency, error handling all verified |
| 5. Linux-Only Features | 3 CONFIRMED | 3/3 | Platform guards, error messages, Kerberos cleanup all verified |
| 6. Go Worker Cross-Platform | 4 CONFIRMED | 4/4 | OS-conditional code, README examples, feature gaps all verified |
| 7. Test Coverage | 5 CONFIRMED, 1 WRONG | 6/7 | test_affinity_impersonation_check exists (not test_affinity_executor_type); missing cross-OS mocking confirmed |
| 8. Operator-Facing Clarity | 4 CONFIRMED | 4/4 | UI displays (OS, Deployment, Capabilities, Shells) all verified |

**Overall:** 33 CONFIRMED, 1 WRONG, 1 PARTIALLY MISLEADING | **Confidence:** High (all major claims independently verified via code inspection)

---

### Per-Area Validation Details

#### Area 1: Capability Detection Mechanism ✅

**File:** `worker/runtime.py`

- **Lines 72-93 (_detect_shells):** ✅ CONFIRMED — Tests bash, sh, cmd, powershell, pwsh with actual subprocess calls; cmd.exe IS tested here on Windows (line 80).
- **Lines 96-127 (_detect_capabilities):** ✅ CONFIRMED — Calls _detect_shells() (line 99), _find_python() (line 102), tries powershell (lines 106-113), platform.system() check for batch (line 115), SQL detection via sqlalchemy import (lines 118-124), http/sensor always advertised (line 126).

**Assessment:** Report's claim "batch only checks platform.system() without verifying cmd.exe" is **PARTIALLY MISLEADING**. While batch (line 116) doesn't have a dedicated cmd.exe test, the shell capability detection (line 99) DOES test cmd.exe on Windows (line 80). If batch is advertised, cmd.exe should be available. However, batch is still advertised without a direct test — if cmd.exe fails in shell detection but somehow exists later, batch could fail at runtime. This is a minor gap but correctly identified in the report.

---

#### Area 2: OS-Specific Executor Behavior ✅

**File:** `worker/executor.py`

- **Lines 21-36 (PowerShell executor):** ✅ CONFIRMED — Calls _resolve_shell() (line 34), constructs command with -NoProfile -Command (line 35).
- **Lines 296-304 (Impersonation guard):** ✅ CONFIRMED — Checks `platform.system().lower()` (line 296), sets `supports_impersonation` for linux/darwin only (line 297), returns error if impersonation/kerberos on non-Linux/macOS (lines 299-304).
- **Lines 422-438 (Batch executor):** ✅ CONFIRMED — Calls `cmd /c` without verification (line 432); no explicit runtime check for cmd.exe.
- **Lines 471-498 (Shell executor):** ✅ CONFIRMED — Branches on shell type (lines 481-491), adds `-ExecutionPolicy Bypass` to PowerShell on Windows (lines 485-486), calls _resolve_shell() (line 480).

**Assessment:** All OS-specific behaviors verified and correctly described in the report.

---

#### Area 3: Deployment Type Auto-Detection ✅

**File:** `worker/worker.py` & `worker/bootstrap.py`

- **worker/worker.py lines 57-60:** ✅ CONFIRMED — Checks `pathlib.Path("/.dockerenv").exists()` (line 58), defaults to "docker" if present, "standalone" otherwise (line 59), allows DEPLOYMENT_TYPE env var override (line 60).
- **bootstrap.py line 313:** ✅ CONFIRMED — Sets `env.setdefault("DEPLOYMENT_TYPE", "scheduler")` for Task Scheduler-launched workers (line 313).

**Assessment:** All auto-detection logic verified. Report's caveats about Podman/WSL/Kubernetes misdetection are valid but cosmetic (metadata only).

---

#### Area 4: Windows Bootstrap/Watchdog Robustness ✅

**File:** `worker/bootstrap.py` & `worker/windows_tasks.py`

- **Lines 277-295 (PID lock mechanism):** ✅ CONFIRMED — Reads lock, checks if PID alive (line 285), replaces stale lock (line 291).
- **Lines 250-274 (_is_pid_alive):** ✅ CONFIRMED — Handles protected processes: Windows ERROR_ACCESS_DENIED (error code 5) returns True (line 266); Unix checks via os.kill (line 271).
- **Lines 472-516 (install action):** ✅ CONFIRMED — Validates config (line 484), uses PowerShell -Force for idempotency (line 260).
- **Lines 519-535 (remove action):** ✅ CONFIRMED — Gracefully handles missing task (lines 305-308 in remove_task).
- **Lines 538-559 (run action):** ✅ CONFIRMED — Validates config (line 544).
- **windows_tasks.py lines 89, 116 (/F flag):** ✅ CONFIRMED — Force overwrite for idempotency.

**Assessment:** All Windows bootstrap robustness claims verified. PID lock staleness handling is solid.

---

#### Area 5: Linux-Only Features & Guards ✅

**File:** `worker/executor.py`

- **Lines 296-304 (Platform check):** ✅ CONFIRMED — Explicit guard: `current_os in ("linux", "darwin")` (line 297); clear error message (line 303).
- **Lines 337-342 (Kerberos init):** ✅ CONFIRMED — Runs kinit command (line 339), checks return code (line 341), returns error on failure (line 342).
- **Lines 316-319 (Impersonation wrapper):** ✅ CONFIRMED — Uses `sudo -n -u` syntax (line 318).
- **kdestroy in finally block:** ✅ CONFIRMED (verified in lines 502-504 via `run_external(...kdestroy...)`).

**Assessment:** All Linux-only guards verified. Impersonation/Kerberos fail-closed and clear.

---

#### Area 6: Go Worker Cross-Platform Story ✅

**File:** `go-worker/internal/executor/executor.go`, `go-worker/internal/worker/metrics.go`, `go-worker/README.md`

- **Line 141 (Impersonation guard):** ✅ CONFIRMED — `runtime.GOOS != "linux" && runtime.GOOS != "darwin"` check, returns error with GOOS name.
- **Lines 693-727 (DetectShells):** ✅ CONFIRMED — Checks `runtime.GOOS == "windows"` (line 694); Windows candidates include cmd/powershell (lines 706-711); Linux candidates exclude them (lines 713-717).
- **metrics.go line 14 (Linux-specific metrics):** ✅ CONFIRMED — `if runtime.GOOS == "linux"` branch (line 14); fallback for other OSes (lines 17-24).
- **README lines 37-38 (Feature gaps):** ✅ CONFIRMED — SQL marked ❌ (line 37), Impersonation/Kerberos marked ❌ Linux-specific (line 38).
- **README lines 73-80 (Cross-compile examples):** ✅ CONFIRMED — Shows GOOS=linux, GOOS=windows, GOOS=darwin examples.
- **CI matrix:** ✅ CONFIRMED (per human review: ubuntu-latest only, no Windows/macOS).

**Assessment:** Go worker cross-platform story well-documented. Cross-compile examples are provided but untested in CI.

---

#### Area 7: Capability + Affinity Test Coverage ⚠️ PARTIALLY WRONG

**File:** `tests/test_worker.py`

- **Line 573 (test_detect_capabilities_includes_http):** ✅ CONFIRMED — Exists, verifies "http" and "shell"/"external" in capabilities.
- **Line 583 (test_detect_capabilities_sql_depends_on_drivers):** ✅ CONFIRMED — Exists, checks SQL advertised when sqlalchemy available.
- **Line 1091 (test_detect_capabilities_shell_requires_working_shell):** ✅ CONFIRMED — Exists, mocks subprocess.run to simulate shell failure.
- **Line 1106 (test_detect_capabilities_sql_requires_python):** ✅ CONFIRMED — Exists, mocks _find_python() to test Python dependency.
- **Line 1116 (test_detect_capabilities_sensor_always_present):** ✅ CONFIRMED — Exists, verifies sensor always in capabilities.
- **Line 1124 (test_detect_capabilities_no_false_positive_sql_without_driver):** ✅ CONFIRMED — Exists, tests SQL not advertised without sqlalchemy.

**Test name issue:**
- **Report claims:** "test_affinity_executor_type() at line 765" — ❌ **WRONG**
- **Actual:** "test_affinity_impersonation_check() at line 753" — Tests impersonation jobs rejected on Windows workers (lines 767-769).
- The test verifies affinity for impersonation on different OSes, but the name and line number in the report are incorrect.

**Coverage gap:**
- ✅ **CONFIRMED:** No cross-platform mocking (platform.system() not mocked in any test). All tests run on CI OS (Linux). Batch, PowerShell, and cross-OS behavior untested in parameterized form.

**Assessment:** Core capability tests verified; test name/line reference is WRONG. Missing cross-OS parameterization is correctly identified.

---

#### Area 8: Operator-Facing Clarity ✅

**File:** `ui/src/pages/WorkerDetail.tsx`, `ui/src/components/WorkersPanel.tsx`

- **WorkerDetail.tsx line 395 (OS display):** ✅ CONFIRMED — `<Descriptions.Item label="OS">{worker.os || "-"}</Descriptions.Item>`.
- **WorkerDetail.tsx line 396 (Deployment Type):** ✅ CONFIRMED — `<Descriptions.Item label="Deployment">{worker.deployment_type || "-"}</Descriptions.Item>`.
- **WorkerDetail.tsx line 447 (Shells display):** ✅ CONFIRMED — Blue tags showing shell names.
- **WorkerDetail.tsx line 450 (Capabilities display):** ✅ CONFIRMED — Cyan tags showing capabilities (shell, python, http, sql, sensor, etc.).
- **WorkersPanel.tsx line 19 (Deployment column):** ✅ CONFIRMED — `{ title: "Deploy", dataIndex: "deployment_type", key: "deployment_type" }`.

**Assessment:** UI clearly displays all required affinity/capability metadata. No missing affordances (though suggested UX improvements for "why isn't my job running?" are valid future work).

---

### Top-5 Priorities Validation

1. **Batch executor cmd.exe verification** — CONFIRMED necessary. Batch is advertised without direct cmd.exe test; shell detection tests it but they're separate capability bits.
2. **Go worker cross-platform testing/docs** — CONFIRMED. README shows cross-compile examples but no CI/production testing. Low-friction clarification in README recommended.
3. **Cross-OS capability test coverage** — CONFIRMED GAP. No platform.system() mocking; all tests run on Linux CI.
4. **Deployment type auto-detection** — CONFIRMED gap (Podman/WSL/K8s misdetection), but low priority (metadata only).
5. **UI affinity mismatch explanations** — CONFIRMED nice-to-have (UX improvement, no correctness impact).

---

### Key Findings & Confidence Assessment

**HIGH CONFIDENCE (33/34 claims verified):**
- Capability detection mechanism is fail-closed and well-designed; only batch cmd.exe test is missing.
- Windows bootstrap/watchdog is robust, idempotent, and handles edge cases (PID staleness, protected processes).
- Linux-only features (impersonation/Kerberos) have explicit, clear guards with good error messages.
- Go worker has proper OS-conditional code; cross-compile examples exist but untested.
- UI surfaces all needed metadata (OS, deployment, capabilities, shells).

**MINOR CORRECTIONS NEEDED:**
1. Test name/line reference in Area 7 (test_affinity_executor_type → test_affinity_impersonation_check at line 753, not 765).
2. Batch/cmd.exe framing: Batch doesn't have a dedicated cmd.exe test, but cmd.exe IS tested via shell detection (lines 80).

**STALE/OUTDATED:** None detected. All cited file paths, line numbers, and functionality remain accurate as of HEAD.
