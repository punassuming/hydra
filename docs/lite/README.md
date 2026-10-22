# Hydra, lite edition

A single-host, database-free scheduler for one user on one machine (Windows first, Linux too). No Redis, MongoDB or
Docker: one background daemon keeps its state in a SQLite file, supervises worker processes, and exposes the same
HTTP API as the full edition, so **`hydra-ctl` works against either**.

## Run it

```bash
uv run hydra-ctl lite daemon start          # background; or `run` to stay in the foreground
uv run hydra-ctl lite daemon status
uv run hydra-ctl apply -f job.yaml          # job.yaml is the same schema as the full edition
uv run hydra-ctl run my-job --param KEY=VALUE --wait
uv run hydra-ctl get runs                   # history; `describe run <id>`, `logs <id> -f`
uv run hydra-ctl lite daemon stop
```

`hydra-ctl` finds the daemon's token automatically for `http://127.0.0.1:8000`; for another host set
`HYDRA_API_URL` and `HYDRA_TOKEN`. Exit codes: 0 ok, 1 error, 3 server unreachable, 4 not found, 5 `run --wait`
finished non-success.

## Where things live

| What | Windows | Linux |
|---|---|---|
| config (`config.toml`) | `%APPDATA%\Hydra` | `~/.config/hydra` |
| data (`hydra.db`, `token`, `logs/`, `workers/`) | `%LOCALAPPDATA%\Hydra` | `~/.local/share/hydra` |

`HYDRA_CONFIG_DIR` / `HYDRA_DATA_DIR` override both. `hydra-ctl lite config path|show|init` prints or writes them.
Precedence: CLI flags > `HYDRA_*` environment > `config.toml` > defaults.

## Workers

The daemon supervises worker processes (`HYDRA_WORKER_MODE=subprocess`, the default): it restarts crashed ones,
starts more when pending work exceeds free capacity (up to `HYDRA_MAX_WORKERS`), and stops idle extras after
`idle_stop_seconds`. `hydra-ctl worker spawn --tag gpu` / `worker stop <id>` manage them by hand.
`HYDRA_WORKER_MODE=inproc` runs a thread pool inside the daemon instead (one process, less isolation).

Jobs may carry `affinity` (`tags`, `os`, `executor_types`...), matched against each worker's registration exactly as
in the full edition. A job nobody can run stays `pending`.

## Scheduling behaviour

* `schedule.timezone` is honoured for cron (IANA name; DST gaps and repeats fire once per local wall-clock time).
* `misfire_policy`: what to do about ticks missed while the daemon was down or the machine asleep: `run_once`
  (default, collapse into one run), `skip`, or `catch_up` (up to `catch_up_limit` runs).
* `overlap_policy`: `allow` (default), `skip` (record a `schedule_events` row, create no run), or `queue` (wait for the
  job's previous run). **`allow` lets the queue grow without bound if jobs are scheduled faster than they run**; use
  `skip` or `queue` for anything that can fall behind.
* Retries (`max_retries`, `retry_delay_seconds`) use the full edition's exponential backoff with jitter, and the delay
  is stored on the run, so a daemon restart does not lose it.
* Runs left active by a crash are marked failed (`lost: ...`) and then retried per policy. Execution is therefore
  **at-least-once** for jobs with retries: a job killed mid-flight may have partly run before its retry starts.

## History and retention

Every run, its state changes (`run_events`), and each job edit (`job_versions`) are kept in SQLite; output is stored as
files under `logs/`. `HYDRA_RUN_RETENTION_DAYS` (lite default **90**, `0` keeps everything) purges older runs,
events and logs. Scheduler bookkeeping (a tick advancing `next_run_at`) is not a job edit and creates no version.

## Security

The API binds to `127.0.0.1` and requires the token (`x-api-key` or `Authorization: Bearer`), stored with
owner-only permissions on Linux. Binding to another address works but is not encrypted; keep it on loopback unless
you front it with TLS. Jobs run as the user that runs the daemon; impersonation and Kerberos are not available.

## Not in the lite edition

Domains and per-domain tokens, Redis ACLs, the web UI, AI features and investigations, credentials, backfill,
`sql`/`sensor` executors (for now), and `HYDRA_MODE=api`. These answer `501 not supported by this Hydra edition`.
