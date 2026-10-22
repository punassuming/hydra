"""SQLite-backed state for Hydra lite.

One connection guarded by a lock; the daemon is the only writer. Queue claims
are a single ``UPDATE ... RETURNING`` inside ``BEGIN IMMEDIATE`` so concurrent
claimers can never receive the same run.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from scheduler.models.job_run import TERMINAL_STATES

SCHEMA_VERSION = 1
MIN_SQLITE = (3, 35, 0)

# Run states are the full edition's (scheduler/models/job_run.py); lite adds none. How a run ended
# (killed, lost...) lives in completion_reason and the run_events type, not in a new status.
TERMINAL_STATUSES = tuple(sorted(TERMINAL_STATES))
OPEN_STATUSES = ("pending", "dispatched", "running")


class NotFound(LookupError):
    pass


class DuplicateJobName(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def norm_ts(value: Any) -> Optional[str]:
    """Normalise a datetime or ISO string to the store's sortable UTC format."""
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return iso(value)


def _enabled(body: dict, default: bool = True) -> int:
    if "enabled" in body:
        return 1 if body["enabled"] else 0
    return 1 if (body.get("schedule") or {}).get("enabled", default) else 0


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


class Store:
    def __init__(self, path: Path | str):
        if sqlite3.sqlite_version_info < MIN_SQLITE:
            raise RuntimeError(f"SQLite {'.'.join(map(str, MIN_SQLITE))}+ is required (found {sqlite3.sqlite_version})")
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._memory = self.path == ":memory:"
        self._local = threading.local()
        self._readers: list[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # ------------------------------------------------------------------ infra
    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(f"database schema v{current} is newer than this Hydra (v{SCHEMA_VERSION})")
            if current < 1:
                script = resources.files("hydra_lite.store").joinpath("schema.sql").read_text(encoding="utf-8")
                self._conn.executescript("BEGIN IMMEDIATE;\n" + script + f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")

    @contextlib.contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        """A connection for read-only queries. WAL lets readers run alongside the single writer, so API reads never
        queue behind a claim/finish transaction. (An in-memory database has one connection, shared under the lock.)"""
        if self._memory:
            with self._lock:
                yield self._conn
            return
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA query_only=1")
            self._local.conn = conn
            with self._readers_lock:
                self._readers.append(conn)
        yield conn

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._readers_lock:
            for conn in self._readers:
                conn.close()
            self._readers.clear()
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------- jobs
    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict:
        doc = json.loads(row["definition"])
        doc.update(
            {
                "_id": row["id"],
                "name": row["name"],
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
        return doc

    def create_job(self, doc: dict, changed_by: Optional[str] = None) -> dict:
        job_id = doc.get("_id") or uuid.uuid4().hex
        ts = iso(now_utc())
        body = {k: v for k, v in doc.items() if k not in ("_id", "created_at", "updated_at")}
        name = body.get("name")
        if not name:
            raise ValueError("job requires a name")
        enabled = _enabled(body)
        next_run = norm_ts((body.get("schedule") or {}).get("next_run_at"))
        try:
            with self._tx() as c:
                c.execute(
                    "INSERT INTO jobs (id, name, definition, enabled, next_run_at, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (job_id, name, _dumps(body), enabled, next_run, ts, ts),
                )
                c.execute(
                    "INSERT INTO job_versions (job_id, version, definition, changed_at, changed_by) VALUES (?,?,?,?,?)",
                    (job_id, 1, _dumps(body), ts, changed_by),
                )
        except sqlite3.IntegrityError as exc:
            if "jobs.name" in str(exc):
                raise DuplicateJobName(name) from exc
            raise
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise NotFound(job_id)
        return self._job_row(row)

    def get_job_by_name(self, name: str) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
        if not row:
            raise NotFound(name)
        return self._job_row(row)

    def list_jobs(self, search: Optional[str] = None, limit: int = 100) -> list[dict]:
        sql, args = "SELECT * FROM jobs", []
        if search:
            sql += " WHERE name LIKE ?"
            args.append(f"%{search}%")
        sql += " ORDER BY name LIMIT ?"
        args.append(limit)
        with self._reader() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._job_row(r) for r in rows]

    def update_job(self, job_id: str, patch: dict, changed_by: Optional[str] = None) -> dict:
        """Shallow-merge ``patch`` (top-level keys replace), recording a new version."""
        ts = iso(now_utc())
        try:
            with self._tx() as c:
                row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not row:
                    raise NotFound(job_id)
                body = json.loads(row["definition"])
                body.update({k: v for k, v in patch.items() if k not in ("_id", "created_at", "updated_at")})
                name = body.get("name") or row["name"]
                enabled = _enabled(body, bool(row["enabled"]))
                next_run = norm_ts((body.get("schedule") or {}).get("next_run_at"))
                version = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM job_versions WHERE job_id=?", (job_id,)).fetchone()[0]
                c.execute(
                    "UPDATE jobs SET name=?, definition=?, enabled=?, next_run_at=?, updated_at=? WHERE id=?",
                    (name, _dumps(body), enabled, next_run, ts, job_id),
                )
                c.execute(
                    "INSERT INTO job_versions (job_id, version, definition, changed_at, changed_by) VALUES (?,?,?,?,?)",
                    (job_id, version, _dumps(body), ts, changed_by),
                )
        except sqlite3.IntegrityError as exc:
            if "jobs.name" in str(exc):
                raise DuplicateJobName(patch.get("name")) from exc
            raise
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> None:
        with self._tx() as c:
            if c.execute("DELETE FROM jobs WHERE id=?", (job_id,)).rowcount == 0:
                raise NotFound(job_id)

    def list_versions(self, job_id: str) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT version, changed_at, changed_by FROM job_versions WHERE job_id=? ORDER BY version DESC", (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, job_id: str, version: int) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM job_versions WHERE job_id=? AND version=?", (job_id, version)).fetchone()
        if not row:
            raise NotFound(f"{job_id}@{version}")
        return {
            "version": row["version"],
            "changed_at": row["changed_at"],
            "changed_by": row["changed_by"],
            "definition": json.loads(row["definition"]),
        }

    def due_jobs(self, now: datetime) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
                (iso(now),),
            ).fetchall()
        return [self._job_row(r) for r in rows]

    # ------------------------------------------------------------------- runs
    @classmethod
    def _run_row_from(cls, row: sqlite3.Row) -> dict:
        row = {k: row[k] for k in row.keys() if not k.startswith("_")}
        return cls._run_row(row)

    @staticmethod
    def _run_row(row: sqlite3.Row | dict) -> dict:
        run = dict(row)
        run["params"] = json.loads(run["params"] or "{}")
        run["sla_miss_alerted"] = bool(run["sla_miss_alerted"])
        run["_id"] = run["id"]
        return run

    def enqueue_run(
        self,
        job_id: str,
        trigger: str = "manual",
        params: Optional[dict] = None,
        priority: int = 5,
        scheduled_ts: Optional[datetime] = None,
        not_before: Optional[datetime] = None,
        retry_attempt: int = 0,
        exclusive: bool = False,
    ) -> dict:
        run_id = uuid.uuid4().hex
        ts = iso(now_utc())
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise NotFound(job_id)
            c.execute(
                "INSERT INTO runs (id, job_id, status, trigger, params, priority, scheduled_ts, queued_at, not_before,"
                " retry_attempt, exclusive) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    job_id,
                    "pending",
                    trigger,
                    _dumps(params or {}),
                    priority,
                    iso(scheduled_ts) if scheduled_ts else None,
                    ts,
                    iso(not_before) if not_before else None,
                    retry_attempt,
                    1 if exclusive else 0,
                ),
            )
            self._event(c, run_id, "queued", {"trigger": trigger, "retry_attempt": retry_attempt})
        return self.get_run(run_id)

    def claim_run(
        self,
        worker_id: str,
        now: Optional[datetime] = None,
        accept: Optional[Callable[[dict, Optional[dict]], bool]] = None,
        scan: int = 50,
    ) -> Optional[dict]:
        """Atomically hand the best eligible pending run to ``worker_id`` (or None).

        ``accept(run, job)`` lets the caller veto runs this worker may not take (affinity, capabilities);
        the best ``scan`` candidates are examined in priority order and the first accepted one is claimed.
        ``job`` is None when the run's job was deleted (the caller decides how to fail it).
        """
        now = now or now_utc()
        ts = iso(now)
        with self._tx() as c:
            rows = c.execute(
                "SELECT r.*, j.definition AS _definition, j.name AS _job_name FROM runs r LEFT JOIN jobs j ON j.id=r.job_id"
                " WHERE r.status='pending' AND (r.not_before IS NULL OR r.not_before<=?)"
                " AND NOT (r.exclusive=1 AND EXISTS (SELECT 1 FROM runs r2 WHERE r2.job_id=r.job_id"
                " AND r2.status IN ('dispatched','running')))"
                " ORDER BY r.priority DESC, r.queued_at, r.rowid LIMIT ?",
                (ts, scan if accept else 1),
            ).fetchall()
            for cand in rows:
                if accept is not None:
                    job = None
                    if cand["_definition"] is not None:
                        job = json.loads(cand["_definition"])
                        job.update({"_id": cand["job_id"], "name": cand["_job_name"]})
                    if not accept(self._run_row_from(cand), job):
                        continue
                row = c.execute(
                    "UPDATE runs SET status='dispatched', worker_id=?, dispatched_at=?, queue_latency_ms="
                    " CAST((julianday(?) - julianday(queued_at)) * 86400000 AS INTEGER)"
                    " WHERE id=? AND status='pending' RETURNING *",
                    (worker_id, ts, ts, cand["id"]),
                ).fetchone()
                if row:
                    self._event(c, row["id"], "dispatched", {"worker_id": worker_id})
                    return self._run_row(row)
        return None

    def has_pending(self, now: Optional[datetime] = None) -> bool:
        """Cheap read-only check so idle workers polling for work never take the write lock."""
        with self._reader() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM runs WHERE status='pending' AND (not_before IS NULL OR not_before<=?) LIMIT 1",
                    (iso(now or now_utc()),),
                ).fetchone()
                is not None
            )

    def requeue_run(self, run_id: str, reason: str) -> bool:
        """Put a dispatched (never started) run back to pending, e.g. when its worker vanished."""
        with self._tx() as c:
            n = c.execute(
                "UPDATE runs SET status='pending', worker_id=NULL, dispatched_at=NULL WHERE id=? AND status='dispatched'",
                (run_id,),
            ).rowcount
            if n:
                self._event(c, run_id, "requeued", {"reason": reason})
            return bool(n)

    def start_run(self, run_id: str, log_path: Optional[str] = None) -> None:
        ts = iso(now_utc())
        with self._tx() as c:
            n = c.execute(
                "UPDATE runs SET status='running', start_ts=?, log_path=COALESCE(?, log_path) WHERE id=? AND status='dispatched'",
                (ts, log_path, run_id),
            ).rowcount
            if n == 0:
                raise NotFound(run_id)
            self._event(c, run_id, "started", {})

    def finish_run(
        self,
        run_id: str,
        status: str,
        returncode: Optional[int] = None,
        completion_reason: Optional[str] = None,
        attempt: Optional[int] = None,
        event_type: Optional[str] = None,
        timings: Optional[dict] = None,
    ) -> tuple[dict, bool]:
        """Move a run to a terminal ``status``. Returns ``(run, changed)``.

        The first terminal transition wins; later calls are no-ops with ``changed=False``, so callers
        can run post-run actions (retry, webhooks, dependents) exactly once. ``event_type`` lets the
        audit trail say *how* it ended (``killed``, ``lost``) without a new status.
        """
        if status not in TERMINAL_STATES:
            raise ValueError(f"not a terminal status: {status}")
        end = now_utc()
        with self._tx() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise NotFound(run_id)
            if row["status"] in TERMINAL_STATES:
                return self._run_row(row), False
            total = None
            if row["start_ts"]:
                total = int((end - datetime.fromisoformat(row["start_ts"])).total_seconds() * 1000)
            c.execute(
                "UPDATE runs SET status=?, returncode=?, completion_reason=?, end_ts=?, total_run_ms=?,"
                " attempt=COALESCE(?, attempt), source_fetch_ms=COALESCE(?, source_fetch_ms),"
                " env_prep_ms=COALESCE(?, env_prep_ms) WHERE id=?",
                (
                    status,
                    returncode,
                    completion_reason,
                    iso(end),
                    total,
                    attempt,
                    (timings or {}).get("source_fetch_ms"),
                    (timings or {}).get("env_prep_ms"),
                    run_id,
                ),
            )
            self._event(
                c, run_id, event_type or status, {"status": status, "returncode": returncode, "reason": completion_reason}
            )
        return self.get_run(run_id), True

    def get_run(self, run_id: str) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise NotFound(run_id)
        return self._run_row(row)

    def list_runs(
        self,
        job_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        before: Optional[str] = None,
    ) -> list[dict]:
        """Newest first. ``before`` is a ``queued_at`` cursor (exclusive)."""
        clauses, args = [], []
        if job_id:
            clauses.append("job_id=?")
            args.append(job_id)
        if status:
            clauses.append("status=?")
            args.append(status)
        if before:
            clauses.append("queued_at<?")
            args.append(before)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._reader() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs{where} ORDER BY queued_at DESC, rowid DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [self._run_row(r) for r in rows]

    def trigger_schedule(
        self,
        job_id: str,
        expected_next_run_at: Optional[str],
        next_schedule: dict,
        ticks: list[dict],
        dropped: Optional[dict] = None,
        skip_if_open: bool = False,
    ) -> Optional[list[dict]]:
        """Atomically fire a job's due ticks and advance its schedule.

        Compare-and-set on ``next_run_at``: if the job was disabled, edited or already advanced since the caller
        planned (e.g. a user ``disable`` racing the trigger loop), nothing happens and ``None`` is returned, so a
        stale plan can neither re-enable a job nor fire a tick twice. Scheduler bookkeeping is *not* a job edit:
        it bumps neither ``updated_at`` nor ``job_versions``. ``ticks`` items: ``{scheduled_ts, priority, exclusive}``.
        """
        created: list[str] = []
        with self._tx() as c:
            row = c.execute("SELECT enabled, next_run_at FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or not row["enabled"] or row["next_run_at"] != expected_next_run_at:
                return None
            nxt = norm_ts(next_schedule.get("next_run_at"))
            c.execute(
                "UPDATE jobs SET definition=json_set(definition, '$.schedule', json(?)), next_run_at=?, enabled=? WHERE id=?",
                (_dumps(next_schedule), nxt, 1 if next_schedule.get("enabled", True) else 0, job_id),
            )
            if dropped:
                c.execute(
                    "INSERT INTO schedule_events (job_id, ts, type, detail) VALUES (?,?,?,?)",
                    (job_id, iso(now_utc()), "misfire_dropped", _dumps(dropped)),
                )
            for tick in ticks:
                if (
                    skip_if_open
                    and c.execute(
                        "SELECT 1 FROM runs WHERE job_id=? AND status IN ('pending','dispatched','running') LIMIT 1", (job_id,)
                    ).fetchone()
                ):
                    c.execute(
                        "INSERT INTO schedule_events (job_id, ts, type, detail) VALUES (?,?,?,?)",
                        (job_id, iso(now_utc()), "overlap_skipped", _dumps({"tick": tick["scheduled_ts"].isoformat()})),
                    )
                    continue
                run_id = uuid.uuid4().hex
                ts = iso(now_utc())
                c.execute(
                    "INSERT INTO runs (id, job_id, status, trigger, params, priority, scheduled_ts, queued_at, exclusive)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        job_id,
                        "pending",
                        "schedule",
                        "{}",
                        tick["priority"],
                        iso(tick["scheduled_ts"]),
                        ts,
                        1 if tick.get("exclusive") else 0,
                    ),
                )
                self._event(c, run_id, "queued", {"trigger": "schedule", "retry_attempt": 0})
                created.append(run_id)
        return [self.get_run(r) for r in created]

    def count_jobs(self) -> int:
        with self._reader() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def upcoming_jobs(self, limit: int = 50) -> list[dict]:
        """Enabled jobs with the soonest ``next_run_at`` (uses the (enabled, next_run_at) index; no JSON scan)."""
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL ORDER BY next_run_at LIMIT ?", (limit,)
            ).fetchall()
        return [self._job_row(r) for r in rows]

    def get_jobs(self, job_ids: list[str]) -> dict[str, dict]:
        """Several jobs in one query (missing ids are simply absent)."""
        ids = list(dict.fromkeys(job_ids))
        if not ids:
            return {}
        with self._reader() as conn:
            rows = conn.execute(f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r["id"]: self._job_row(r) for r in rows}

    def count_by_status(self) -> dict[str, int]:
        with self._reader() as conn:
            return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status")}

    def seconds_until_next_due(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds until the earliest enabled schedule fires (<= 0 if overdue); None if nothing is scheduled."""
        with self._reader() as conn:
            row = conn.execute("SELECT MIN(next_run_at) AS t FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL").fetchone()
        if not row or not row["t"]:
            return None
        return (datetime.fromisoformat(row["t"]) - (now or now_utc())).total_seconds()

    def count_runs(self, status: str) -> int:
        with self._reader() as conn:
            return conn.execute("SELECT COUNT(*) FROM runs WHERE status=?", (status,)).fetchone()[0]

    def open_run_count(self, job_id: str) -> int:
        """Runs of ``job_id`` that are pending, dispatched or running."""
        with self._reader() as conn:
            return conn.execute(
                f"SELECT COUNT(*) FROM runs WHERE job_id=? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
                (job_id, *OPEN_STATUSES),
            ).fetchone()[0]

    def running_runs(self) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute("SELECT * FROM runs WHERE status='running'").fetchall()
        return [self._run_row(r) for r in rows]

    def active_run_ids(self) -> list[str]:
        """Runs a worker has taken (dispatched/running) but not finished."""
        with self._reader() as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM runs WHERE status IN ('dispatched','running')")]

    def mark_sla_alerted(self, run_id: str) -> bool:
        """Set ``sla_miss_alerted`` once; True only for the caller that flipped it."""
        with self._tx() as c:
            return c.execute("UPDATE runs SET sla_miss_alerted=1 WHERE id=? AND sla_miss_alerted=0", (run_id,)).rowcount == 1

    def find_dependents(self, job_id: str) -> list[dict]:
        """Enabled jobs whose ``depends_on`` contains ``job_id``."""
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT j.* FROM jobs j WHERE j.enabled=1 AND EXISTS ("
                " SELECT 1 FROM json_each(j.definition, '$.depends_on') d WHERE d.value=?)",
                (job_id,),
            ).fetchall()
        return [self._job_row(r) for r in rows]

    def purge_runs_before(self, cutoff: datetime) -> list[str]:
        """Delete finished runs (and their events) that ended before ``cutoff``; return the run ids."""
        with self._tx() as c:
            ids = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM runs WHERE end_ts IS NOT NULL AND end_ts<?"
                    f" AND status IN ({','.join('?' * len(TERMINAL_STATES))})",
                    (iso(cutoff), *TERMINAL_STATES),
                )
            ]
            for run_id in ids:
                c.execute("DELETE FROM run_events WHERE run_id=?", (run_id,))
                c.execute("DELETE FROM runs WHERE id=?", (run_id,))
            c.execute("DELETE FROM schedule_events WHERE ts<?", (iso(cutoff),))
        return ids

    def recover_orphans(self, reason: str = "lost: daemon restarted while the run was active") -> list[dict]:
        """Fail runs left dispatched/running with no live owner; returns the runs that were changed."""
        changed = []
        for run_id in self.active_run_ids():
            run, did = self.finish_run(run_id, "failed", completion_reason=reason, event_type="lost")
            if did:
                changed.append(run)
        return changed

    # ----------------------------------------------------------------- events
    def _event(self, c: sqlite3.Connection, run_id: str, type_: str, detail: dict) -> None:
        c.execute(
            "INSERT INTO run_events (run_id, ts, type, detail) VALUES (?,?,?,?)",
            (run_id, iso(now_utc()), type_, _dumps(detail)),
        )

    def add_event(self, run_id: str, type_: str, detail: Optional[dict] = None) -> None:
        with self._tx() as c:
            self._event(c, run_id, type_, detail or {})

    def add_schedule_event(self, job_id: str, type_: str, detail: Optional[dict] = None) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO schedule_events (job_id, ts, type, detail) VALUES (?,?,?,?)",
                (job_id, iso(now_utc()), type_, _dumps(detail or {})),
            )

    def list_schedule_events(self, job_id: str) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute("SELECT ts, type, detail FROM schedule_events WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [{"ts": r["ts"], "type": r["type"], "detail": json.loads(r["detail"])} for r in rows]

    def list_events(self, run_id: str) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute("SELECT ts, type, detail FROM run_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{"ts": r["ts"], "type": r["type"], "detail": json.loads(r["detail"])} for r in rows]

    # ---------------------------------------------------------------- workers
    def register_worker(
        self,
        worker_id: str,
        pid: Optional[int],
        max_concurrency: int = 1,
        tags: Optional[list] = None,
        capabilities: Optional[list] = None,
        meta: Optional[dict] = None,
    ) -> None:
        ts = iso(now_utc())
        with self._tx() as c:
            c.execute(
                "INSERT INTO workers (id, pid, started_at, last_heartbeat, state, max_concurrency, tags, capabilities, meta)"
                " VALUES (?,?,?,?, 'online', ?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET pid=excluded.pid, started_at=excluded.started_at,"
                " last_heartbeat=excluded.last_heartbeat, max_concurrency=excluded.max_concurrency,"
                " tags=excluded.tags, capabilities=excluded.capabilities, meta=excluded.meta,"
                " state=CASE WHEN workers.state='offline' THEN 'online' ELSE workers.state END",
                (worker_id, pid, ts, ts, max_concurrency, _dumps(tags or []), _dumps(capabilities or []), _dumps(meta or {})),
            )

    def get_worker(self, worker_id: str) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        if not row:
            raise NotFound(worker_id)
        return self._worker_row(row)

    @staticmethod
    def _worker_row(row: sqlite3.Row) -> dict:
        w = dict(row)
        w["tags"] = json.loads(w["tags"])
        w["capabilities"] = json.loads(w["capabilities"])
        w["meta"] = json.loads(w["meta"] or "{}")
        return w

    def stale_workers(self, cutoff: datetime) -> list[dict]:
        """Workers whose last heartbeat is older than ``cutoff`` (regardless of operator-set state)."""
        with self._reader() as conn:
            rows = conn.execute("SELECT * FROM workers WHERE last_heartbeat<?", (iso(cutoff),)).fetchall()
        return [self._worker_row(r) for r in rows]

    def delete_worker(self, worker_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM workers WHERE id=?", (worker_id,))

    def worker_runs(self, worker_id: str, statuses: tuple[str, ...] = ("dispatched", "running")) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs WHERE worker_id=? AND status IN ({','.join('?' * len(statuses))})", (worker_id, *statuses)
            ).fetchall()
        return [self._run_row(r) for r in rows]

    def heartbeat(self, worker_id: str) -> None:
        with self._tx() as c:
            if c.execute("UPDATE workers SET last_heartbeat=? WHERE id=?", (iso(now_utc()), worker_id)).rowcount == 0:
                raise NotFound(worker_id)

    def set_worker_state(self, worker_id: str, state: str) -> None:
        with self._tx() as c:
            if c.execute("UPDATE workers SET state=? WHERE id=?", (state, worker_id)).rowcount == 0:
                raise NotFound(worker_id)

    def list_workers(self) -> list[dict]:
        with self._reader() as conn:
            rows = conn.execute("SELECT * FROM workers ORDER BY id").fetchall()
        return [self._worker_row(r) for r in rows]
