# Worker Framework & Protocol Investigation

**Investigation Date:** 2026-09-25  
**Scope:** Python `worker/` vs Go `go-worker/` — shared Redis protocol & env-var contract  
**Status:** IN PROGRESS

---

## 1. Registration & Discovery Protocol
*Investigating: Redis keys, data shapes, TTLs, scheduler consumption*

### Under Investigation...

---

## 2. Heartbeat Protocol
*Investigating: interval, TTL, metrics fields, graceful degradation*

### Under Investigation...

---

## 3. Dispatch Queue Protocol
*Investigating: envelope format, BLPOP shape, executor-type parsing*

### Under Investigation...

---

## 4. Run Event Protocol
*Investigating: run_start/run_end shape, timing fields, missing-field handling*

### Under Investigation...

---

## 5. Log Streaming Protocol
*Investigating: per-domain channels, chunk/format consistency, SSE/UI compatibility*

### Under Investigation...

---

## 6. Worker Operations Log Protocol
*Investigating: event types, shapes, timeline rendering completeness*

### Under Investigation...

---

## 7. Capability Negotiation & Affinity
*Investigating: capability advertisement, fail-closed detection, dispatcher trust*

### Under Investigation...

---

## 8. State/Lifecycle Protocol
*Investigating: online/draining/offline handling, dispatch gate behavior*

### Under Investigation...

---

## 9. Protocol Versioning & Drift Risk
*Investigating: explicit version fields, implicit compatibility, silent-break risks*

### Under Investigation...

---

## Summary — Top 5 Priorities
*To be completed after investigation*

