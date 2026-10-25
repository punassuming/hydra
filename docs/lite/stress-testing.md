# Stress testing the lite edition

`scripts/lite_stress.py` starts a **real daemon process with supervised worker processes** in a temp directory, drives
it only through the public API, can `kill -9` its processes, and checks invariants. It never runs in default CI.

```bash
uv run python scripts/lite_stress.py --profile smoke                 # ~2 minutes
uv run python scripts/lite_stress.py --profile full --out report.json   # ~25 minutes incl. a 10-minute soak
uv run python scripts/lite_stress.py --only burst,chaos --runs 5000 --probe-threads 0   # raw throughput
HYDRA_STRESS=1 uv run pytest tests/lite/test_stress_smoke.py           # smoke profile as a pytest (Linux)
```

| Scenario | What it does | Invariants checked |
|---|---|---|
| `burst` | thousands of manual runs from 16 client threads while API endpoints are probed | every run succeeds, **executes exactly once** (per-run marker file), no API errors |
| `schedules` | 200 interval jobs (1 s) for 90 s | each job fires its expected ticks (no misses, **no extras**); trigger drift |
| `overload` | scheduled load far above capacity, `overlap_policy` `skip` vs `allow` | `skip` keeps the queue bounded by the job count and records skipped ticks |
| `history` | 100,000 finished runs + 10,000 jobs already in the database | endpoint latency; retention purges old runs and their events |
| `logs` | 64 MB of output and 20,000 short lines | stored bytes equal emitted bytes; reading a big log stays cheap |
| `chaos` | `kill -9` of workers mid-run and of the daemon itself during a burst | nothing stuck, nothing lost, nothing run twice without a recorded loss |
| `soak` | 10 minutes of mixed load | process RSS and thread count do not grow without bound |

## Reference results

4 CPUs / 16 GB sandbox, SQLite on local disk, Python 3.11, external-executor marker jobs (the `shell` executor starts a
login shell, `bash -lc`, which costs ~120 ms of CPU per run on this machine; use `--executor shell` to include that).
Absolute numbers will differ elsewhere; the ratios and the invariants are the point.

| | Result |
|---|---|
| Burst throughput | ~105 runs/s raw (4 workers x 8 slots), ~85 runs/s while 3 threads hammer the API; 0 API errors in 1,540 probe requests |
| Submit rate | ~170-240 `POST /jobs/{id}/run` per second |
| API p95 under that load | `/health` 25 ms, `/workers/` 42 ms, `/overview/queue` 55 ms, `/history/?limit=100` 96 ms |
| Schedules | 18,253 runs from 200 jobs at 1 s; every job fired 91-92 times in 90 s; trigger drift p50 9 ms, p95 39 ms, p99 209 ms |
| Overload | `overlap_policy: skip` peaked at 148 pending (150 jobs) with 4,404 ticks skipped; `allow` reached 4,404 pending and was still growing |
| Big history (100k runs, 10k jobs) | `/history/?limit=100` 8 ms, `/history/?paged=true` 5 ms, `/history/?limit=1000` 69 ms, `/jobs/` p50 115 ms / p95 540 ms, `/overview/statistics` 71 ms; retention (30 d) purged 100,000 to 14,999 runs with no orphaned events |
| Logs | 64 MB in 2.5 s, byte-exact; `GET /runs/{id}` on it 21 ms |
| Chaos | 8 worker kills + 1 daemon kill during 600 runs: 20 runs recovered as `lost` and retried, all 600 logical runs succeeded, none executed twice without a recorded loss |
| Soak (10 min, 2,359 manual + 10 interval jobs) | 21,522 API probes, 0 errors; p95 under 21 ms; daemon RSS <= 85 MB, 19 threads; database 6.7 MB |

## What it found (and was fixed)

1. **Disabling a job could be silently undone.** The trigger loop wrote back a schedule it had read earlier, so a
   `disable` landing in between was overwritten and the job kept firing. Triggering is now one transaction that
   compare-and-sets `next_run_at` (`Store.trigger_schedule`).
2. **Every scheduled tick created a job version** (437 versions for one job in five minutes). Scheduler bookkeeping is
   not an edit, so it no longer touches `job_versions` or `updated_at`.
3. **Retention never ran after a fresh boot** because the loop compared against `time.monotonic()`, whose origin is
   arbitrary and can be smaller than the check interval.
4. **API latency collapsed under write load**: all reads shared the writer's connection and lock (`/overview/queue`
   p95 1.3 s with 3,000 pending). Reads now use per-thread read-only WAL connections (p95 55 ms), at a cost of
   roughly 5 % raw throughput. `/overview/queue` and `/overview/statistics` also stopped parsing every job definition.
5. **Trigger ticks were up to a second late** (fixed 1 s sleep); the loop now sleeps until the next due schedule.
6. **A worker restarted under the same id hid its lost runs** from the reaper; registration and heartbeats now
   reconcile the runs a worker no longer holds.
7. **Draining workers stopped heartbeating**, so the reaper failed their in-flight runs; they now beat until they exit.
8. Generated tokens could start with `-`, which `argparse` reads as a flag (flaky CLI tests); tokens are now hex.

## Known limits (design, not bugs)

* `overlap_policy: allow` (the default) lets the pending queue grow without bound when jobs are scheduled faster than
  they run. Use `skip` or `queue` for anything that can fall behind.
* One SQLite writer: roughly 100+ run lifecycles per second on this hardware, bounded by process spawn, not by the
  database. Thousands of runs per second is out of scope for this edition.
* `/jobs/` parses every job definition: ~0.1 s per 10,000 jobs.
* A shell job pays the login-shell startup of the full edition's executor.
* Windows has not been stress-tested (the harness reads `/proc`); run `smoke` on a Windows host by hand before relying on it.
