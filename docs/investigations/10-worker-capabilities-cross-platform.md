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
(To be updated as investigation proceeds...)

---

## 4. Windows Bootstrap/Watchdog Robustness

*Investigating: `worker/bootstrap.py` and `worker/windows_tasks.py` — install/remove/validate idempotency and error handling.*

### Findings
(To be updated as investigation proceeds...)

---

## 5. Linux-Only Features & Guards

*Investigating: impersonation and Kerberos — platform checks and error clarity on non-Linux workers.*

### Findings
(To be updated as investigation proceeds...)

---

## 6. Go Worker Cross-Platform Story

*Investigating: Go worker build matrix, OS-conditional code, and positioning (Linux/container-only vs. multi-platform).*

### Findings
(To be updated as investigation proceeds...)

---

## 7. Capability + Affinity Test Coverage

*Investigating: tests exercising capability detection across simulated OS conditions — coverage gaps.*

### Findings
(To be updated as investigation proceeds...)

---

## 8. Operator-Facing Clarity

*Investigating: UI display of worker OS, deployment type, and advertised capabilities.*

### Findings
(To be updated as investigation proceeds...)

---

## Summary — Top 5 Priorities

(To be completed after investigation concludes...)
