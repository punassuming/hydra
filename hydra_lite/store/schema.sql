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

CREATE TABLE runs (
    id               TEXT PRIMARY KEY,
    job_id           TEXT NOT NULL,
    status           TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    params           TEXT NOT NULL DEFAULT '{}',
    priority         INTEGER NOT NULL DEFAULT 5,
    scheduled_for    TEXT,
    queued_at        TEXT NOT NULL,
    not_before       TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    exit_code        INTEGER,
    attempt          INTEGER NOT NULL DEFAULT 0,
    worker_id        TEXT,
    reason           TEXT,
    log_path         TEXT,
    queue_latency_ms INTEGER,
    total_run_ms     INTEGER
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
