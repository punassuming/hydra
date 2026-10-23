-- Artifacts published by runs (stdout marker) and consumed through jobs' triggers_on_artifacts.
CREATE TABLE artifacts (
    name         TEXT PRIMARY KEY,
    last_updated TEXT NOT NULL,
    last_run_id  TEXT,
    last_job_id  TEXT,
    metadata     TEXT NOT NULL DEFAULT '{}'
);
