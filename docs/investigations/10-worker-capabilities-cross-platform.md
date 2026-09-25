# Worker Capability Detection & Cross-Platform Support Investigation

**Date Started:** 2026-09-25  
**Status:** In Progress

---

## 1. Capability Detection Mechanism

*Investigating: `worker/runtime.py` and `_detect_capabilities()` in `worker/executor.py` — preflight checks for each executor type.*

### Findings
(To be updated as investigation proceeds...)

---

## 2. OS-Specific Executor Behavior

*Investigating: shell/batch/powershell executors — correct OS-specific selection and graceful unavailability on mismatched platforms.*

### Findings
(To be updated as investigation proceeds...)

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
