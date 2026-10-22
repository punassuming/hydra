#!/usr/bin/env python3
"""Stress test for the Hydra lite edition.

Starts a REAL daemon process (with supervised worker processes) in a temp directory, drives it only through
its public API, can kill -9 its processes, and checks invariants:

  * every submitted run reaches a terminal state and is never lost
  * a run executes at most once (exactly once if it succeeded) -- verified with per-run marker files
  * the API stays responsive under load

Usage:
    uv run python scripts/lite_stress.py --profile smoke            # ~1-2 minutes
    uv run python scripts/lite_stress.py --profile full --out report.json
    uv run python scripts/lite_stress.py --only burst,chaos --runs 5000

Linux only for resource sampling (reads /proc); everything else is portable. Never runs in default CI.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cli._client import APIError, HydraClient  # noqa: E402

EXECUTOR = "external"
PROBE_THREADS = 3  # API probe threads during the burst (0 = measure raw throughput)

PROFILES: dict[str, dict[str, Any]] = {
    "smoke": dict(
        burst_runs=300,
        burst_workers=2,
        burst_conc=4,
        clients=8,
        sched_jobs=40,
        sched_interval=2,
        sched_seconds=14,
        overload_seconds=12,
        history_runs=20_000,
        history_jobs=500,
        logs_mb=8,
        chaos_runs=150,
        chaos_kills=3,
        soak_seconds=0,
    ),
    "full": dict(
        burst_runs=3000,
        burst_workers=4,
        burst_conc=8,
        clients=16,
        sched_jobs=200,
        sched_interval=1,
        sched_seconds=90,
        overload_seconds=30,
        history_runs=100_000,
        history_jobs=10_000,
        logs_mb=64,
        chaos_runs=600,
        chaos_kills=8,
        soak_seconds=600,
    ),
}


# ------------------------------------------------------------------ helpers
def pct(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * p / 100))], 1)


def summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": pct(values, 50),
        "p95": pct(values, 95),
        "p99": pct(values, 99),
        "max": round(max(values), 1) if values else None,
    }


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def children_of(pid: int) -> list[int]:
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == pid:
            out.append(int(entry))
    return out


def descendants(pid: int) -> list[int]:
    found, frontier = [], [pid]
    while frontier:
        kids = [c for p in frontier for c in children_of(p)]
        found += kids
        frontier = kids
    return found


def rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def thread_count(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("Threads:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


class Harness:
    """One daemon process in a temp dir, plus a resource sampler."""

    def __init__(
        self,
        profile: dict,
        workers: int = 2,
        conc: int = 4,
        max_workers: int = 4,
        ttl: float = 4.0,
        retention: int = 0,
        mode: str = "subprocess",
    ):
        self.profile = profile
        self.tmp = Path(tempfile.mkdtemp(prefix="hydra-stress-"))
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = {
            **os.environ,
            "HYDRA_DATA_DIR": str(self.tmp / "data"),
            "HYDRA_CONFIG_DIR": str(self.tmp / "cfg"),
            "HYDRA_PORT": str(self.port),
            "HYDRA_WORKER_MODE": mode,
            "HYDRA_DEFAULT_WORKERS": str(workers),
            "HYDRA_MAX_WORKERS": str(max_workers),
            "HYDRA_MAX_CONCURRENCY": str(conc),
            "SCHEDULER_HEARTBEAT_TTL": str(ttl),
            "HYDRA_RUN_RETENTION_DAYS": str(retention),
        }
        self.proc: Optional[subprocess.Popen] = None
        self.samples: list[dict] = []
        self._sampling = threading.Event()
        self.api: Optional[HydraClient] = None
        self.out = self.tmp / "out"
        self.out.mkdir()

    @property
    def db_path(self) -> Path:
        return self.tmp / "data" / "hydra.db"

    def start(self, wait_workers: int = 1) -> None:
        (self.tmp / "data").mkdir(exist_ok=True)
        log = open(self.tmp / "daemon.log", "ab")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "hydra_lite"], env=self.env, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT)
        )
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                HydraClient(self.url, timeout=2).health()
                break
            except APIError:
                time.sleep(0.2)
        else:
            raise RuntimeError("daemon did not start; see " + str(self.tmp / "daemon.log"))
        token = (self.tmp / "data" / "token").read_text().strip()
        self.api = HydraClient(self.url, token=token, timeout=60)
        self.wait_workers(wait_workers)

    def wait_workers(self, n: int, timeout: float = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if sum(w["connectivity_status"] == "online" for w in self.api.request("GET", "/workers/")) >= n:
                    return
            except APIError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"fewer than {n} workers came online")

    def stop(self) -> None:
        self._sampling.set()
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(40)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def kill_daemon(self) -> None:
        assert self.proc
        self.proc.kill()
        self.proc.wait()

    def worker_pids(self) -> list[int]:
        return [w["pid"] for w in self.api.request("GET", "/workers/") if w.get("pid") and w["connectivity_status"] == "online"]

    def sample_loop(self, every: float = 2.0) -> None:
        def run():
            while not self._sampling.wait(every):
                if not self.proc or self.proc.poll() is not None:
                    continue
                kids = descendants(self.proc.pid)
                self.samples.append(
                    {
                        "t": time.time(),
                        "daemon_rss": rss_mb(self.proc.pid),
                        "daemon_threads": thread_count(self.proc.pid),
                        "tree_rss": rss_mb(self.proc.pid) + sum(rss_mb(k) for k in kids),
                        "procs": 1 + len(kids),
                        "db_mb": self.db_path.stat().st_size / 1e6 if self.db_path.exists() else 0,
                        "wal_mb": (self.db_path.with_name("hydra.db-wal").stat().st_size / 1e6)
                        if self.db_path.with_name("hydra.db-wal").exists()
                        else 0,
                    }
                )

        threading.Thread(target=run, daemon=True).start()

    def db(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30)
        con.row_factory = sqlite3.Row
        return con


def noop_executor() -> dict:
    if EXECUTOR == "shell":
        return {"type": "shell", "script": "true"}
    return {"type": "external", "command": "/bin/true"}


def submit_job(api: HydraClient, name: str, script: str, **extra) -> dict:
    return api.request(
        "POST",
        "/jobs/",
        body={
            "name": name,
            "executor": {"type": "shell", "script": script},
            "schedule": {"mode": "cron", "cron": "0 0 1 1 *"},
            **extra,
        },
    )


MARK = 'printf x >> "$OUT/$RID"'  # one byte per execution, so duplicates and losses are visible


def marker_job(api: HydraClient, name: str, prefix: str = "", **extra) -> dict:
    """A job that appends one byte to $OUT/$RID. Uses the *external* executor (plain /bin/sh -c) on purpose: the
    shell executor starts a login shell (bash -lc, ~120 ms of profile scripts here), which would measure the
    machine's shell startup instead of the scheduler. ``--executor shell`` switches to the real thing."""
    if EXECUTOR == "shell":
        return submit_job(api, name, prefix + MARK, **extra)
    body = {
        "name": name,
        "executor": {"type": "external", "command": "/bin/sh", "args": ["-c", prefix + MARK]},
        "schedule": {"mode": "cron", "cron": "0 0 1 1 *"},
        **extra,
    }
    return api.request("POST", "/jobs/", body=body)


def read_marks(out: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in out.iterdir()}


def wait_drained(h: Harness, expected: int, timeout: float) -> float:
    """Wait until no run is pending/dispatched/running; return seconds waited."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            con = h.db()
            open_runs = con.execute("SELECT COUNT(*) FROM runs WHERE status IN ('pending','dispatched','running')").fetchone()[0]
            con.close()
        except sqlite3.OperationalError:
            open_runs = 1
        if open_runs == 0:
            return time.time() - t0
        time.sleep(0.5)
    raise TimeoutError(f"runs still open after {timeout:.0f}s")


class ApiProbe:
    """Hammers read endpoints from background threads and records latency/errors per endpoint."""

    ENDPOINTS = ["/health", "/jobs/", "/workers/", "/overview/queue", "/overview/pressure", "/history/?limit=100"]

    def __init__(self, h: Harness, threads: int = 3):
        self.h, self.n = h, threads
        self.lat: dict[str, list[float]] = {e: [] for e in self.ENDPOINTS}
        self.errors = 0
        self.total = 0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def __enter__(self):
        for _ in range(self.n):
            t = threading.Thread(target=self._run, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def _run(self):
        api = HydraClient(self.h.url, token=self.h.api.headers["x-api-key"], timeout=30)
        while not self._stop.is_set():
            for e in self.ENDPOINTS:
                t0 = time.perf_counter()
                try:
                    api.request("GET", e)
                    self.lat[e].append((time.perf_counter() - t0) * 1000)
                except Exception:
                    self.errors += 1
                self.total += 1
                if self._stop.wait(0.05):
                    return

    def __exit__(self, *exc):
        self._stop.set()
        for t in self._threads:
            t.join(5)

    def report(self) -> dict:
        return {"requests": self.total, "errors": self.errors, "latency_ms": {e: summary(v) for e, v in self.lat.items()}}


# ---------------------------------------------------------------- scenarios
def burst(p: dict) -> dict:
    """Many manual runs at once, while the API is probed. Exactly-once is checked with marker files."""
    h = Harness(p, workers=p["burst_workers"], conc=p["burst_conc"], max_workers=p["burst_workers"])
    h.start(p["burst_workers"])
    h.sample_loop()
    violations: list[str] = []
    try:
        job = marker_job(h.api, "burst")
        n = p["burst_runs"]

        def one(i: int):
            return h.api.request("POST", f"/jobs/{job['_id']}/run", body={"params": {"RID": f"r{i}", "OUT": str(h.out)}})[
                "run_id"
            ]

        t0 = time.time()
        with ApiProbe(h, PROBE_THREADS) as probe:
            with ThreadPoolExecutor(p["clients"]) as pool:
                ids = list(pool.map(one, range(n)))
            submit_s = time.time() - t0
            drain_s = wait_drained(h, n, timeout=max(120, n / 3))
        total_s = time.time() - t0
        con = h.db()
        rows = con.execute("SELECT id, status, queue_latency_ms, start_ts, end_ts, queued_at FROM runs").fetchall()
        con.close()
        from datetime import datetime

        def ms(a, b):
            return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000

        qlat = [r["queue_latency_ms"] for r in rows if r["queue_latency_ms"] is not None]
        e2e = [ms(r["queued_at"], r["end_ts"]) for r in rows if r["end_ts"]]
        marks = read_marks(h.out)
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if by_status.get("success", 0) != n:
            violations.append(f"expected {n} successes, got {by_status}")
        dupes = {k: v for k, v in marks.items() if v != 1}
        if dupes or len(marks) != n:
            violations.append(f"exactly-once violated: {len(marks)} markers for {n} runs, {len(dupes)} with size != 1")
        if len(set(ids)) != n:
            violations.append("duplicate run ids returned")
        if probe.errors:
            violations.append(f"{probe.errors} API errors under load")
        return {
            "runs": n,
            "workers": p["burst_workers"],
            "concurrency_per_worker": p["burst_conc"],
            "submit_rate_per_s": round(n / submit_s, 1),
            "submit_seconds": round(submit_s, 1),
            "drain_seconds_after_submit": round(drain_s, 1),
            "throughput_runs_per_s": round(n / total_s, 1),
            "queue_latency_ms": summary(qlat),
            "end_to_end_ms": summary(e2e),
            "statuses": by_status,
            "api_under_load": probe.report(),
            "resources": resource_summary(h),
            "violations": violations,
        }
    finally:
        h.stop()


def resource_summary(h: Harness) -> dict:
    s = h.samples
    if not s:
        return {}
    return {
        "daemon_rss_mb_max": round(max(x["daemon_rss"] for x in s), 1),
        "tree_rss_mb_max": round(max(x["tree_rss"] for x in s), 1),
        "daemon_threads_max": max(x["daemon_threads"] for x in s),
        "procs_max": max(x["procs"] for x in s),
        "db_mb_max": round(max(x["db_mb"] for x in s), 2),
        "wal_mb_max": round(max(x["wal_mb"] for x in s), 2),
    }


def schedules(p: dict) -> dict:
    """Many interval jobs at once: trigger drift and missed/duplicated ticks."""
    h = Harness(p, workers=2, conc=8, max_workers=2)
    h.start(2)
    h.sample_loop()
    violations: list[str] = []
    try:
        interval, secs, jobs = p["sched_interval"], p["sched_seconds"], p["sched_jobs"]
        for i in range(jobs):
            h.api.request(
                "POST",
                "/jobs/",
                body={
                    "name": f"tick-{i}",
                    "executor": noop_executor(),
                    "schedule": {"mode": "interval", "interval_seconds": interval},
                },
            )
        time.sleep(secs)
        for j in h.api.request("GET", "/jobs/"):
            h.api.request("POST", f"/jobs/{j['_id']}/disable")
        wait_drained(h, 0, 300)
        con = h.db()
        rows = con.execute("SELECT job_id, scheduled_ts, queued_at, status FROM runs WHERE trigger='schedule'").fetchall()
        con.close()
        from datetime import datetime

        drift = [
            (datetime.fromisoformat(r["queued_at"]) - datetime.fromisoformat(r["scheduled_ts"])).total_seconds() * 1000
            for r in rows
            if r["scheduled_ts"]
        ]
        per_job: dict[str, int] = {}
        for r in rows:
            per_job[r["job_id"]] = per_job.get(r["job_id"], 0) + 1
        expected = secs / interval
        outliers = sorted(per_job.items(), key=lambda kv: -kv[1])[:3]
        long_runs = [c for _, c in outliers if c > expected * 1.5]
        if long_runs:
            violations.append(f"jobs fired far more than the {expected:.0f} expected ticks: {outliers}")
        short = [c for c in per_job.values() if c < expected * 0.8]
        if short:
            violations.append(
                f"{len(short)}/{jobs} jobs fired fewer than 80% of {expected:.0f} expected ticks (min {min(per_job.values())})"
            )
        if len(per_job) < jobs:
            violations.append(f"{jobs - len(per_job)} jobs never fired")
        failed = sum(1 for r in rows if r["status"] != "success")
        if failed:
            violations.append(f"{failed} scheduled runs did not succeed")
        return {
            "jobs": jobs,
            "interval_s": interval,
            "seconds": secs,
            "runs": len(rows),
            "expected_per_job": round(expected, 1),
            "runs_per_job": summary(list(per_job.values())),
            "trigger_drift_ms": summary(drift),
            "resources": resource_summary(h),
            "violations": violations,
        }
    finally:
        h.stop()


def overload(p: dict) -> dict:
    """Offered scheduled load far above capacity. With overlap_policy=skip the queue must stay bounded; with the
    default (allow) it grows without bound -- reported, not failed, because that is the documented policy."""
    jobs, secs = 150, p["overload_seconds"]
    results: dict[str, Any] = {}
    violations: list[str] = []
    for policy in ("skip", "allow"):
        h = Harness(p, workers=1, conc=2, max_workers=1)
        h.start(1)
        try:
            for i in range(jobs):
                body = {
                    "name": f"hot-{i}",
                    "executor": {"type": "external", "command": "/bin/sleep", "args": ["0.5"]}
                    if EXECUTOR != "shell"
                    else {"type": "shell", "script": "sleep 0.5"},
                    "schedule": {"mode": "interval", "interval_seconds": 1, "overlap_policy": policy},
                }
                h.api.request("POST", "/jobs/", body=body)
            peak, end = 0, time.time() + secs
            while time.time() < end:
                peak = max(peak, h.api.request("GET", "/overview/pressure")["pending"])
                time.sleep(1)
            for j in h.api.request("GET", "/jobs/"):
                h.api.request("POST", f"/jobs/{j['_id']}/disable")
            con = h.db()
            skipped = con.execute("SELECT COUNT(*) FROM schedule_events WHERE type='overlap_skipped'").fetchone()[0]
            runs = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            con.close()
            results[policy] = {"peak_pending": peak, "runs_created": runs, "overlap_skipped_events": skipped}
            if policy == "skip" and peak > jobs:
                violations.append(f"overlap_policy=skip let the queue reach {peak} (> {jobs} jobs)")
            if policy == "skip" and not skipped:
                violations.append("overlap_policy=skip recorded no skipped ticks while overloaded")
        finally:
            h.stop()
    return {**results, "violations": violations}


def seed_history(db_path: Path, n: int, extra_jobs: int = 0) -> None:
    """Insert ``n`` finished runs directly (before the daemon starts) to emulate a long-lived install."""
    sys.path.insert(0, str(ROOT))
    from hydra_lite.store import Store

    store = Store(db_path)
    job = store.create_job(
        {
            "name": "history-seed",
            "executor": {"type": "shell", "script": "true"},
            "schedule": {"mode": "cron", "cron": "0 0 1 1 *", "enabled": False},
        }
    )
    from datetime import datetime, timedelta, timezone

    for i in range(extra_jobs):  # a big job catalogue: schedules disabled, so only list/lookup cost shows
        store.create_job(
            {
                "name": f"catalogue-{i}",
                "executor": {"type": "shell", "script": "true"},
                "schedule": {"mode": "interval", "interval_seconds": 86400, "enabled": False},
            }
        )
    base = datetime.now(timezone.utc) - timedelta(days=200)
    rows = []
    for i in range(n):
        t = base + timedelta(seconds=i * (200 * 86400 / n))
        ts = t.isoformat(timespec="milliseconds")
        rows.append((f"seed{i:08d}", job["_id"], "success", "schedule", "{}", 5, ts, ts, ts, ts, 0, 1, ts))
    with store._tx() as c:  # noqa: SLF001 - bulk seeding
        c.executemany(
            "INSERT INTO runs (id, job_id, status, trigger, params, priority, scheduled_ts, queued_at, start_ts, end_ts,"
            " returncode, attempt, dispatched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        c.executemany(
            "INSERT INTO run_events (run_id, ts, type, detail) VALUES (?,?,?,?)",
            [(r[0], r[7], t, "{}") for r in rows for t in ("queued", "dispatched", "started", "success")],
        )
    store.close()


def history(p: dict) -> dict:
    """API latency and retention cost against a large pre-existing history."""
    n = p["history_runs"]
    h = Harness(p, workers=1, conc=4, max_workers=1, retention=30)
    (h.tmp / "data").mkdir()
    t0 = time.time()
    seed_history(h.db_path, n, p["history_jobs"])
    seed_s = time.time() - t0
    h.start(1)
    h.sample_loop()
    violations: list[str] = []
    try:
        # retention (30 days) will purge ~85% of the seed in the first maintenance pass
        lat: dict[str, list[float]] = {}
        endpoints = [
            "/health",
            "/jobs/",
            "/jobs/?search=catalogue-77",
            "/history/?limit=100",
            "/history/?limit=1000",
            "/history/?paged=true&limit=50",
            "/overview/queue",
            "/overview/statistics",
            "/workers/",
        ]
        for e in endpoints:
            lat[e] = []
            for _ in range(15):
                t = time.perf_counter()
                try:
                    h.api.request("GET", e)
                    lat[e].append((time.perf_counter() - t) * 1000)
                except APIError as exc:
                    violations.append(f"{e}: {exc}")
                    break
        time.sleep(8)  # let the retention pass run
        con = h.db()
        remaining = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        orphan_events = con.execute("SELECT COUNT(*) FROM run_events WHERE run_id NOT IN (SELECT id FROM runs)").fetchone()[0]
        con.close()
        if orphan_events:
            violations.append(f"{orphan_events} run_events left behind by retention")
        slow = {e: s["p95"] for e, v in lat.items() if (s := summary(v))["p95"] and s["p95"] > 1000}
        if slow:
            violations.append(f"p95 over 1s with {n} runs of history: {slow}")
        return {
            "seeded_runs": n,
            "seed_seconds": round(seed_s, 1),
            "runs_after_retention": remaining,
            "latency_ms": {e: summary(v) for e, v in lat.items()},
            "resources": resource_summary(h),
            "violations": violations,
        }
    finally:
        h.stop()


def logs(p: dict) -> dict:
    """Large and chatty output: integrity of the stored log and the cost of reading it back."""
    h = Harness(p, workers=1, conc=2, max_workers=1)
    h.start(1)
    h.sample_loop()
    violations: list[str] = []
    try:
        mb = p["logs_mb"]
        big = submit_job(
            h.api,
            "big-output",
            f"python3 -c \"import sys\nline='y'*1023+'\\n'\nfor _ in range({mb}*1024): sys.stdout.write(line)\"",
        )
        small = submit_job(h.api, "many-lines", 'i=0; while [ $i -lt 20000 ]; do echo "line $i"; i=$((i+1)); done')
        t0 = time.time()
        r1 = h.api.request("POST", f"/jobs/{big['_id']}/run", body={})["run_id"]
        r2 = h.api.request("POST", f"/jobs/{small['_id']}/run", body={})["run_id"]
        wait_drained(h, 2, 600)
        elapsed = time.time() - t0
        sizes = {}
        for name, rid in (("big", r1), ("lines", r2)):
            files = list((h.tmp / "data" / "logs").glob(f"*/*/{rid}.out"))
            sizes[name] = files[0].stat().st_size if files else -1
        if sizes["big"] != mb * 1024 * 1024:
            violations.append(f"big log is {sizes['big']} bytes, expected {mb * 1024 * 1024}")
        expect_lines = sum(len(f"line {i}\n") for i in range(20000))
        if sizes["lines"] != expect_lines:
            violations.append(f"line log is {sizes['lines']} bytes, expected {expect_lines}")
        t = time.perf_counter()
        run = h.api.request("GET", f"/runs/{r1}")
        read_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        chunk = h.api.request("GET", f"/runs/{r1}/logs", query={"out_offset": 5 * 1024 * 1024})
        tail_ms = (time.perf_counter() - t) * 1000
        if run["status"] != "success":
            violations.append(f"big-output run ended {run['status']}: {run.get('completion_reason')}")
        return {
            "big_mb": mb,
            "seconds": round(elapsed, 1),
            "mb_per_s": round(mb / elapsed, 1),
            "log_bytes": sizes,
            "get_run_ms": round(read_ms, 1),
            "get_log_chunk_ms": round(tail_ms, 1),
            "chunk_bytes": len(chunk["stdout"]),
            "resources": resource_summary(h),
            "violations": violations,
        }
    finally:
        h.stop()


def chaos(p: dict) -> dict:
    """kill -9 workers and then the daemon mid-burst. Nothing may be lost, stuck, or run twice."""
    h = Harness(p, workers=3, conc=4, max_workers=3, ttl=4.0)
    h.start(3)
    h.sample_loop()
    violations: list[str] = []
    try:
        n = p["chaos_runs"]
        # a short sleep widens the window in which a kill lands mid-run; retries let lost runs finish
        job = marker_job(h.api, "chaos", "sleep 0.3; ", max_retries=3)

        def one(i: int):
            for _ in range(40):
                try:
                    return h.api.request("POST", f"/jobs/{job['_id']}/run", body={"params": {"RID": f"r{i}", "OUT": str(h.out)}})[
                        "run_id"
                    ]
                except APIError:
                    time.sleep(0.5)  # daemon restarting
            return None

        with ThreadPoolExecutor(8) as pool:
            futures = [pool.submit(one, i) for i in range(n)]
            kills = 0
            rng = random.Random(7)
            time.sleep(2)
            for k in range(p["chaos_kills"]):
                pids = h.worker_pids()
                if pids:
                    try:
                        os.kill(rng.choice(pids), signal.SIGKILL)
                        kills += 1
                    except ProcessLookupError:
                        pass
                time.sleep(2.5)
                if k == p["chaos_kills"] // 2:  # kill the daemon itself (workers survive and must notice)
                    h.kill_daemon()
                    time.sleep(1)
                    h.start(1)
            submitted = [f.result() for f in futures]
        missing = sum(1 for s in submitted if s is None)
        if missing:
            violations.append(f"{missing} submissions never accepted")
        drain_s = wait_drained(h, n, timeout=300)
        con = h.db()
        rows = con.execute("SELECT id, status, retry_attempt, completion_reason, params FROM runs").fetchall()
        con.close()
        by_rid: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            rid = json.loads(r["params"]).get("RID")
            by_rid.setdefault(rid, []).append(r)
        marks = read_marks(h.out)
        never_succeeded = [rid for rid, rs in by_rid.items() if not any(x["status"] == "success" for x in rs)]
        # at-least-once with retries: duplicates are legal only when an earlier execution was lost/killed mid-flight
        over = {
            rid: size
            for rid, size in marks.items()
            if size > 1 and not any("lost" in (x["completion_reason"] or "") for x in by_rid.get(rid, []))
        }
        if over:
            violations.append(f"{len(over)} runs executed more than once without a recorded loss, e.g. {list(over.items())[:3]}")
        if len(by_rid) != n - missing:
            violations.append(f"expected {n - missing} logical runs, found {len(by_rid)}")
        if never_succeeded:
            violations.append(f"{len(never_succeeded)} runs never succeeded even with retries, e.g. {never_succeeded[:3]}")
        lost = sum(1 for r in rows if "lost" in (r["completion_reason"] or ""))
        return {
            "runs": n,
            "worker_kills": kills,
            "daemon_kills": 1,
            "lost_runs_recovered": lost,
            "total_run_rows": len(rows),
            "drain_seconds_after_chaos": round(drain_s, 1),
            "resources": resource_summary(h),
            "violations": violations,
        }
    finally:
        h.stop()


def soak(p: dict) -> dict:
    """Sustained mixed load; resource use must not grow without bound."""
    secs = p["soak_seconds"]
    if secs <= 0:
        return {"skipped": "soak_seconds=0 in this profile", "violations": []}
    h = Harness(p, workers=2, conc=4, max_workers=2, retention=1)
    h.start(2)
    h.sample_loop(5.0)
    violations: list[str] = []
    try:
        job = submit_job(h.api, "soak", 'echo "$RID"')
        for i in range(10):
            h.api.request(
                "POST",
                "/jobs/",
                body={
                    "name": f"soak-tick-{i}",
                    "executor": {"type": "shell", "script": "true"},
                    "schedule": {"mode": "interval", "interval_seconds": 2},
                },
            )
        end, i = time.time() + secs, 0
        with ApiProbe(h, 2) as probe:
            while time.time() < end:
                h.api.request("POST", f"/jobs/{job['_id']}/run", body={"params": {"RID": str(i)}})
                i += 1
                time.sleep(0.25)
        s = h.samples
        if len(s) >= 12:
            third = max(1, len(s) // 3)
            early, late = (
                statistics.mean(x["tree_rss"] for x in s[third : 2 * third]),
                statistics.mean(x["tree_rss"] for x in s[-third:]),
            )
            growth = late - early
            if growth > 50:
                violations.append(f"process-tree RSS grew {growth:.0f} MB between the middle and last third")
            tgrow = s[-1]["daemon_threads"] - s[third]["daemon_threads"]
            if tgrow > 20:
                violations.append(f"daemon thread count grew by {tgrow}")
        if probe.errors:
            violations.append(f"{probe.errors} API errors during soak")
        return {
            "seconds": secs,
            "manual_runs": i,
            "api": probe.report(),
            "resources": resource_summary(h),
            "rss_first_last_mb": [round(s[0]["tree_rss"], 1), round(s[-1]["tree_rss"], 1)] if s else None,
            "violations": violations,
        }
    finally:
        h.stop()


SCENARIOS: dict[str, Callable[[dict], dict]] = {
    "burst": burst,
    "schedules": schedules,
    "overload": overload,
    "history": history,
    "logs": logs,
    "chaos": chaos,
    "soak": soak,
}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    ap.add_argument("--only", help="comma-separated scenarios: " + ",".join(SCENARIOS))
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--runs", type=int, help="override burst_runs")
    ap.add_argument("--probe-threads", type=int, default=3, help="API probe threads during the burst (0 for raw throughput)")
    ap.add_argument("--executor", choices=("external", "shell"), default="external", help="executor for marker jobs")
    args = ap.parse_args(argv)
    global EXECUTOR, PROBE_THREADS
    EXECUTOR = args.executor
    PROBE_THREADS = args.probe_threads
    profile = dict(PROFILES[args.profile])
    if args.runs:
        profile["burst_runs"] = args.runs
    names = args.only.split(",") if args.only else list(SCENARIOS)
    report: dict[str, Any] = {"profile": args.profile, "params": profile, "cpus": os.cpu_count(), "scenarios": {}}
    failed = False
    for name in names:
        print(f"== {name} ...", flush=True)
        t0 = time.time()
        try:
            result = SCENARIOS[name](profile)
        except Exception as exc:  # a crashed scenario is a failure, with the reason recorded
            result = {"violations": [f"scenario crashed: {type(exc).__name__}: {exc}"]}
        result["wall_seconds"] = round(time.time() - t0, 1)
        report["scenarios"][name] = result
        bad = result.get("violations") or []
        failed = failed or bool(bad)
        print(json.dumps(result, indent=2, default=str), flush=True)
        print(f"== {name}: {'FAIL' if bad else 'ok'}", flush=True)
    report["passed"] = not failed
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
