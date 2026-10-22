-- Schema version 1. Timestamps are ISO-8601 UTC strings (lexicographically sortable).
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    definition  TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_jobs_due ON jobs (enabled, next_run_at);

CREATE TABLE job_versions (
    job_id     TEXT NOT NULL,
    version    INTEGER NOT NULL,
    definition TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    changed_by TEXT,
    PRIMARY KEY (job_id, version)
);

-- Column names and status values mirror scheduler/models/job_run.py (JobRun, RunStatus) so both editions
-- describe a run identically. Lite-only columns: trigger, queued_at, not_before, log_path, total_run_ms.
CREATE TABLE runs (
    id               TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL,
    status           TEXT NOT NULL,          -- pending|dispatched|running|success|failed|timed_out
    trigger          TEXT NOT NULL,          -- manual|schedule|immediate_submit|retry|dependency
    params           TEXT NOT NULL DEFAULT '{}',
    priority         INTEGER NOT NULL DEFAULT 5,
    scheduled_ts     TEXT,
    queued_at        TEXT NOT NULL,
    not_before       TEXT,
    start_ts         TEXT,
    end_ts           TEXT,
    returncode       INTEGER,
    attempt          INTEGER NOT NULL DEFAULT 0,       -- in-worker attempts used (job.retries loop)
    retry_attempt    INTEGER NOT NULL DEFAULT 0,       -- scheduler-level retries preceding this run
    worker_id        TEXT,
    completion_reason TEXT,
    log_path         TEXT,
    queue_latency_ms INTEGER,
    total_run_ms     INTEGER,
    sla_miss_alerted INTEGER NOT NULL DEFAULT 0,
    exclusive        INTEGER NOT NULL DEFAULT 0       -- overlap_policy=queue: wait for the job's other runs to end
);
CREATE INDEX idx_runs_queue ON runs (status, priority DESC, queued_at);
CREATE INDEX idx_runs_job ON runs (job_id, queued_at);

CREATE TABLE run_events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts     TEXT NOT NULL,
    type   TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_events_run ON run_events (run_id, id);

-- Scheduling decisions that did not create a run (overlap skipped, missed ticks dropped...).
CREATE TABLE schedule_events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts     TEXT NOT NULL,
    type   TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_schedule_events_job ON schedule_events (job_id, id);

CREATE TABLE workers (
    id             TEXT PRIMARY KEY,
    pid            INTEGER,
    started_at     TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'online',
    max_concurrency INTEGER NOT NULL DEFAULT 1,
    tags           TEXT NOT NULL DEFAULT '[]',
    capabilities   TEXT NOT NULL DEFAULT '[]'
);
