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
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 1
MIN_SQLITE = (3, 35, 0)

ACTIVE_STATUSES = ("dispatched", "running")
TERMINAL_STATUSES = ("success", "failed", "timed_out", "killed", "lost", "skipped")


class NotFound(LookupError):
    pass


class DuplicateJobName(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


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
        enabled = 1 if body.get("enabled", True) else 0
        next_run = ((body.get("schedule") or {}).get("next_run_at")) or None
        try:
            with self._tx() as c:
                c.execute(
                    "INSERT INTO jobs (id, name, definition, enabled, next_run_at, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (job_id, name, _dumps(body), enabled, str(next_run) if next_run else None, ts, ts),
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
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise NotFound(job_id)
        return self._job_row(row)

    def get_job_by_name(self, name: str) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
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
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
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
                enabled = 1 if body.get("enabled", bool(row["enabled"])) else 0
                next_run = ((body.get("schedule") or {}).get("next_run_at")) or None
                version = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM job_versions WHERE job_id=?", (job_id,)).fetchone()[0]
                c.execute(
                    "UPDATE jobs SET name=?, definition=?, enabled=?, next_run_at=?, updated_at=? WHERE id=?",
                    (name, _dumps(body), enabled, str(next_run) if next_run else None, ts, job_id),
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
        with self._lock:
            rows = self._conn.execute(
                "SELECT version, changed_at, changed_by FROM job_versions WHERE job_id=? ORDER BY version DESC", (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, job_id: str, version: int) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM job_versions WHERE job_id=? AND version=?", (job_id, version)).fetchone()
        if not row:
            raise NotFound(f"{job_id}@{version}")
        return {
            "version": row["version"],
            "changed_at": row["changed_at"],
            "changed_by": row["changed_by"],
            "definition": json.loads(row["definition"]),
        }

    def due_jobs(self, now: datetime) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
                (iso(now),),
            ).fetchall()
        return [self._job_row(r) for r in rows]

    # ------------------------------------------------------------------- runs
    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict:
        run = dict(row)
        run["params"] = json.loads(run["params"] or "{}")
        run["_id"] = run["id"]
        return run

    def enqueue_run(
        self,
        job_id: str,
        trigger: str = "manual",
        params: Optional[dict] = None,
        priority: int = 5,
        scheduled_for: Optional[datetime] = None,
        not_before: Optional[datetime] = None,
        attempt: int = 0,
    ) -> dict:
        run_id = uuid.uuid4().hex
        ts = iso(now_utc())
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise NotFound(job_id)
            c.execute(
                "INSERT INTO runs (id, job_id, status, trigger, params, priority, scheduled_for, queued_at, not_before, attempt)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    job_id,
                    "queued",
                    trigger,
                    _dumps(params or {}),
                    priority,
                    iso(scheduled_for) if scheduled_for else None,
                    ts,
                    iso(not_before) if not_before else None,
                    attempt,
                ),
            )
            self._event(c, run_id, "queued", {"trigger": trigger, "attempt": attempt})
        return self.get_run(run_id)

    def claim_run(self, worker_id: str, now: Optional[datetime] = None) -> Optional[dict]:
        """Atomically hand the best eligible queued run to ``worker_id`` (or None)."""
        now = now or now_utc()
        ts = iso(now)
        with self._tx() as c:
            row = c.execute(
                "UPDATE runs SET status='dispatched', worker_id=?, queue_latency_ms="
                " CAST((julianday(?) - julianday(queued_at)) * 86400000 AS INTEGER)"
                " WHERE id=(SELECT id FROM runs WHERE status='queued' AND (not_before IS NULL OR not_before<=?)"
                " ORDER BY priority DESC, queued_at, rowid LIMIT 1) RETURNING *",
                (worker_id, ts, ts),
            ).fetchone()
            if not row:
                return None
            self._event(c, row["id"], "dispatched", {"worker_id": worker_id})
        return self._run_row(row)

    def start_run(self, run_id: str, log_path: Optional[str] = None) -> None:
        ts = iso(now_utc())
        with self._tx() as c:
            n = c.execute(
                "UPDATE runs SET status='running', started_at=?, log_path=COALESCE(?, log_path), attempt=attempt+1"
                " WHERE id=? AND status='dispatched'",
                (ts, log_path, run_id),
            ).rowcount
            if n == 0:
                raise NotFound(run_id)
            self._event(c, run_id, "started", {})

    def finish_run(
        self,
        run_id: str,
        status: str,
        exit_code: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> dict:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"not a terminal status: {status}")
        end = now_utc()
        with self._tx() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise NotFound(run_id)
            if row["status"] in TERMINAL_STATUSES:
                return self._run_row(row)  # idempotent: first terminal state wins
            total = None
            if row["started_at"]:
                total = int((end - datetime.fromisoformat(row["started_at"])).total_seconds() * 1000)
            c.execute(
                "UPDATE runs SET status=?, exit_code=?, reason=?, finished_at=?, total_run_ms=? WHERE id=?",
                (status, exit_code, reason, iso(end), total, run_id),
            )
            self._event(c, run_id, status, {"exit_code": exit_code, "reason": reason})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
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
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM runs{where} ORDER BY queued_at DESC, rowid DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [self._run_row(r) for r in rows]

    def active_run_count(self, job_id: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM runs WHERE job_id=? AND status IN ('queued','dispatched','running')", (job_id,)
            ).fetchone()[0]

    def recover_orphans(self, reason: str = "daemon restarted while run was active") -> list[str]:
        """Mark runs left dispatched/running (no live owner after a restart) as ``lost``."""
        end = iso(now_utc())
        with self._tx() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM runs WHERE status IN ('dispatched','running')")]
            for run_id in ids:
                c.execute("UPDATE runs SET status='lost', reason=?, finished_at=? WHERE id=?", (reason, end, run_id))
                self._event(c, run_id, "lost", {"reason": reason})
        return ids

    # ----------------------------------------------------------------- events
    def _event(self, c: sqlite3.Connection, run_id: str, type_: str, detail: dict) -> None:
        c.execute(
            "INSERT INTO run_events (run_id, ts, type, detail) VALUES (?,?,?,?)",
            (run_id, iso(now_utc()), type_, _dumps(detail)),
        )

    def add_event(self, run_id: str, type_: str, detail: Optional[dict] = None) -> None:
        with self._tx() as c:
            self._event(c, run_id, type_, detail or {})

    def list_events(self, run_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT ts, type, detail FROM run_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{"ts": r["ts"], "type": r["type"], "detail": json.loads(r["detail"])} for r in rows]

    # ---------------------------------------------------------------- workers
    def register_worker(
        self,
        worker_id: str,
        pid: Optional[int],
        max_concurrency: int = 1,
        tags: Optional[list] = None,
        capabilities: Optional[list] = None,
    ) -> None:
        ts = iso(now_utc())
        with self._tx() as c:
            c.execute(
                "INSERT INTO workers (id, pid, started_at, last_heartbeat, state, max_concurrency, tags, capabilities)"
                " VALUES (?,?,?,?, 'online', ?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET pid=excluded.pid, started_at=excluded.started_at,"
                " last_heartbeat=excluded.last_heartbeat, max_concurrency=excluded.max_concurrency,"
                " tags=excluded.tags, capabilities=excluded.capabilities",
                (worker_id, pid, ts, ts, max_concurrency, _dumps(tags or []), _dumps(capabilities or [])),
            )

    def heartbeat(self, worker_id: str) -> None:
        with self._tx() as c:
            if c.execute("UPDATE workers SET last_heartbeat=? WHERE id=?", (iso(now_utc()), worker_id)).rowcount == 0:
                raise NotFound(worker_id)

    def list_workers(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM workers ORDER BY id").fetchall()
        out = []
        for r in rows:
            w = dict(r)
            w["tags"] = json.loads(w["tags"])
            w["capabilities"] = json.loads(w["capabilities"])
            out.append(w)
        return out
