# Windows Worker Bootstrap Guide

This guide explains how to install and manage a Hydra worker on a Windows host
using a single Windows Task Scheduler entry as a bootstrap/watchdog task.

## Overview

Instead of creating many per-job Task Scheduler entries, the Windows Worker
Bootstrap lets you:

1. Register **one** Task Scheduler task per host that launches a lightweight
   watchdog process on system start-up.
2. The watchdog keeps the Hydra worker process alive, restarting it if it
   exits unexpectedly.
3. All actual job scheduling is centralised in the Hydra scheduler — the Task
   Scheduler entry is only responsible for worker lifecycle.

```
Windows Task Scheduler
  └─ Hydra\WorkerBootstrap  (one task per host)
       └─ python -m worker bootstrap run
            └─ [watchdog loop] → starts/restarts "python -m worker"
                                       │
                                       ▼
                              Hydra Worker Process
                              (connects to Redis, receives jobs)
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.13 (3.11+ supported) | Available via [uv](https://github.com/astral-sh/uv) or a standalone installer |
| uv | Recommended for managing the Python virtual environment |
| Hydra worker installed | See **Runtime directory setup** below |
| Redis connection | `REDIS_URL` must be reachable from the Windows host |
| Domain token | Obtain from a Hydra administrator (`API_TOKEN`) |
| Administrator rights | Required only for the `install` step (to create the scheduled task) |

---

## Runtime directory setup

The worker process should run from a **dedicated runtime directory** (e.g.
`C:\hydra-worker\`) that is separate from the source tree.  This keeps
credentials, logs, and the virtual environment isolated from the repository.

```powershell
# Create the runtime directory
New-Item -ItemType Directory -Force C:\hydra-worker
New-Item -ItemType Directory -Force C:\hydra-worker\logs

# Create a virtual environment with uv
cd C:\hydra-worker
uv venv .venv

# Install the Hydra worker package from the source tree
uv pip install -e C:\path\to\hydra
```

Create a `.env` file in `C:\hydra-worker\` with the worker credentials:

```ini
DOMAIN=prod
API_TOKEN=<your-domain-token>
REDIS_URL=redis://<redis-host>:6379/0
REDIS_PASSWORD=<your-redis-acl-password>
HYDRA_BOOTSTRAP_WORKING_DIR=C:\hydra-worker
HYDRA_BOOTSTRAP_LOG_FILE=C:\hydra-worker\logs\worker.log
PYTHONUNBUFFERED=1
```

The bootstrap reads this file automatically on startup — no need to set
environment variables in the shell before running `install` or `run`.

---

## Environment Variables

Configure the worker and bootstrap by setting environment variables in the
service account's user profile (or via a `.env` file loaded before running).

### Required

| Variable | Description | Example |
|---|---|---|
| `DOMAIN` | Hydra domain name | `prod` |
| `API_TOKEN` | Domain API token | `dt_abc123...` |
| `REDIS_URL` | Redis connection URL | `redis://redis.internal:6379/0` |

### Optional (worker)

| Variable | Default | Description |
|---|---|---|
| `REDIS_PASSWORD` | — | Domain-scoped Redis ACL password (if ACL is enabled) |
| `WORKER_ID` | `worker-<hostname>-<pid>` | Unique worker identifier |
| `WORKER_TAGS` | — | Comma-separated affinity tags |
| `MAX_CONCURRENCY` | `2` | Maximum concurrent jobs |
| `WORKER_STATE` | `online` | Initial worker state (`online`/`draining`) |
| `DEPLOYMENT_TYPE` | `scheduler` | Deployment type shown in the UI. Set automatically to `scheduler` by the bootstrap watchdog. Override only if needed (e.g. `standalone` for a manually-launched worker). |

### Optional (bootstrap / watchdog)

| Variable | Default | Description |
|---|---|---|
| `HYDRA_BOOTSTRAP_TASK_NAME` | `\Hydra\WorkerBootstrap` | Task Scheduler task name (may include folder prefix) |
| `HYDRA_BOOTSTRAP_SCHEDULE_TYPE` | `ONSTART` | Trigger type: `ONSTART` or `MINUTE` |
| `HYDRA_BOOTSTRAP_INTERVAL_MINUTES` | `5` | Interval for `MINUTE` trigger |
| `HYDRA_BOOTSTRAP_RUN_AS_SYSTEM` | `false` | Run task as `SYSTEM` account |
| `HYDRA_BOOTSTRAP_WORKER_COMMAND` | `<python> -m worker` | Command used to launch the worker |
| `HYDRA_BOOTSTRAP_WORKING_DIR` | current directory | Working directory for the worker process |
| `HYDRA_BOOTSTRAP_LOG_FILE` | — | Path to redirect worker stdout/stderr |
| `HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL` | `30` | Seconds between watchdog health checks |
| `HYDRA_BOOTSTRAP_LOCK_FILE` | `%TEMP%\hydra_bootstrap.lock` | PID lock file path |

---

## Commands

All commands below assume the runtime directory is `C:\hydra-worker\` with a
`uv`-managed virtual environment at `C:\hydra-worker\.venv\` and credentials
in `C:\hydra-worker\.env`.

### Validate configuration

Check that all required variables are set before installing:

```powershell
cd C:\hydra-worker
.\.venv\Scripts\python.exe -m worker bootstrap validate
```

Expected output:
```
Bootstrap configuration is valid.
  task_name             : \Hydra\WorkerBootstrap
  schedule_type         : ONSTART
  worker_command        : C:\hydra-worker\.venv\Scripts\python.exe -m worker
  working_dir           : 'C:\hydra-worker' (effective)
  lock_file             : C:\Users\svc_hydra\AppData\Local\Temp\hydra_bootstrap.lock
  watchdog_interval (s) : 30
  domain                : prod
```

### Install the scheduled task

Run this **once** (or again to update an existing task) in an **elevated
(administrator) PowerShell session**.  The bootstrap reads credentials from
`.env` automatically — no need to set environment variables in the shell.

```powershell
cd C:\hydra-worker
.\.venv\Scripts\python.exe -m worker bootstrap install
```

Expected output:
```
Task '\Hydra\WorkerBootstrap' installed successfully.
The task will launch the Hydra worker watchdog on the next trigger.
  Trigger        : ONSTART
  Worker command : C:\hydra-worker\.venv\Scripts\python.exe -m worker
```

The task is created via `Register-ScheduledTask` (PowerShell), which stores the
executable path, arguments, and working directory as separate fields — avoiding
the quoting ambiguity of the legacy `schtasks /TR` parameter.

> **Note:** The `install` command is idempotent — running it again is safe and
> will update the task definition in place.

### Start the watchdog immediately (without waiting for reboot)

After installing, you can start the watchdog manually:

```powershell
cd C:\hydra-worker
.\.venv\Scripts\python.exe -m worker bootstrap run
```

This blocks until interrupted (Ctrl+C or process termination).  The Task
Scheduler task will run this command automatically on the next system start-up.

### Remove the scheduled task

```powershell
cd C:\hydra-worker
.\.venv\Scripts\python.exe -m worker bootstrap remove
```

Expected output:
```
Task '\Hydra\WorkerBootstrap' removed (or was not present).
```

> **Note:** Removing the task does **not** stop any currently running worker
> process.  Stop the worker separately if needed.

---

## Complete example (production)

Below is a complete setup script suitable for copy-paste into a PowerShell
provisioning script:

```powershell
# ── Hydra Worker Bootstrap — production setup ──────────────────────────────

# 1. Create the runtime directory and install the worker.
New-Item -ItemType Directory -Force C:\hydra-worker
New-Item -ItemType Directory -Force C:\hydra-worker\logs
cd C:\hydra-worker
uv venv .venv
uv pip install -e C:\path\to\hydra

# 2. Write credentials to .env (replace placeholder values).
@"
DOMAIN=prod
API_TOKEN=dt_REPLACE_WITH_REAL_TOKEN
REDIS_URL=redis://redis.internal:6379/0
REDIS_PASSWORD=REPLACE_WITH_REDIS_ACL_PASSWORD
HYDRA_BOOTSTRAP_WORKING_DIR=C:\hydra-worker
HYDRA_BOOTSTRAP_LOG_FILE=C:\hydra-worker\logs\worker.log
WORKER_TAGS=windows,prod,batch
MAX_CONCURRENCY=4
PYTHONUNBUFFERED=1
"@ | Set-Content C:\hydra-worker\.env

# 3. Validate before installing.
.\.venv\Scripts\python.exe -m worker bootstrap validate
if ($LASTEXITCODE -ne 0) { exit 1 }

# 4. Install (or update) the Task Scheduler entry (requires elevated shell).
.\.venv\Scripts\python.exe -m worker bootstrap install
if ($LASTEXITCODE -ne 0) { exit 1 }

# 5. Start the watchdog immediately (optional — will also start on next reboot).
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m worker bootstrap run" `
    -WorkingDirectory "C:\hydra-worker" -WindowStyle Hidden
```

---

## Operational notes

### Service account

Run the Hydra worker under a **dedicated service account** (e.g.
`DOMAIN\svc_hydra`).  This account should:

- Have `Log on as a batch job` user rights.
- Have read access to the Python installation and Hydra source directory.
- Have write access to the log directory (`HYDRA_BOOTSTRAP_LOG_FILE`).
- Have network access to reach Redis.

### Security

- **Avoid storing tokens in plain text** on disk.  Use Windows Credential
  Manager, Group Policy, or a secrets management tool to inject `API_TOKEN`
  and `REDIS_PASSWORD` into the service account's environment.
- Set `HYDRA_BOOTSTRAP_RUN_AS_SYSTEM=false` (the default) unless you have a
  specific need.  Running as SYSTEM gives the worker elevated access.
- The `install` command requires administrator rights to create the Task
  Scheduler entry, but the watchdog and worker processes themselves do **not**
  need to run elevated.

### Periodic watchdog trigger

The default trigger is `ONSTART` (runs when the system boots).  If you want
the watchdog to also restart automatically if the system is already running,
add a periodic trigger by setting:

```powershell
$env:HYDRA_BOOTSTRAP_SCHEDULE_TYPE   = "MINUTE"
$env:HYDRA_BOOTSTRAP_INTERVAL_MINUTES = "5"
```

This creates a task that runs every 5 minutes.  The watchdog's own internal
PID-lock mechanism prevents duplicate worker processes even if the task
triggers while the watchdog is already running.

### Log rotation

The `HYDRA_BOOTSTRAP_LOG_FILE` target is opened in **append** mode.  Use a
tool such as [NLog](https://nlog-project.org/),
[Serilog](https://serilog.net/), or a scheduled `copy /y` + truncate script
to rotate the file.

---

## Troubleshooting

### "only supported on Windows" error

```
RuntimeError: Windows Task Scheduler management is only supported on Windows.
```

You are running the `install` or `remove` command on Linux or macOS.  These
subcommands only work on Windows.  Use the `validate` and `run` subcommands
on non-Windows hosts for testing.

### Task appears in Task Scheduler but worker does not start

1. Check that `DOMAIN`, `API_TOKEN`, and `REDIS_URL` are set in the **service
   account's environment** (not just the current session).  Run
   `python -m worker bootstrap validate` as the service account.
2. Verify that the Python interpreter path in
   `HYDRA_BOOTSTRAP_WORKER_COMMAND` is correct for the service account.
3. Check the log file (`HYDRA_BOOTSTRAP_LOG_FILE`) for startup errors.
4. Run `python -m worker bootstrap run` interactively as the service account
   to see live output.

### "Access is denied" when running install

The `install` command calls `Register-ScheduledTask` via PowerShell, which
requires administrator rights to create tasks in the `\Hydra\` folder.  Open
PowerShell as Administrator and re-run the command.

### Worker keeps restarting

Check the worker log file for repeated error messages.  Common causes:

- Invalid `API_TOKEN` — the worker fails to register with the scheduler.
- Redis unreachable — check `REDIS_URL` and firewall rules.
- Python missing — verify `HYDRA_BOOTSTRAP_WORKER_COMMAND` points to a valid
  interpreter.

### Duplicate worker processes

The bootstrap uses a PID lock file (`HYDRA_BOOTSTRAP_LOCK_FILE`) to prevent
multiple watchdog processes from spawning.  If you see duplicate workers:

1. Check that no stale lock file exists at the configured path.
2. Ensure only one Task Scheduler task is configured for the host.
3. Delete the stale lock file manually if the watchdog process has exited:
   ```powershell
   Remove-Item $env:TEMP\hydra_bootstrap.lock -ErrorAction SilentlyContinue
   ```

---

## Reference

- [Task Scheduler documentation (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page)
- [`schtasks` command reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks)
- Hydra worker configuration: [`worker/config.py`](../worker/config.py)
- Bootstrap source: [`worker/bootstrap.py`](../worker/bootstrap.py)
- Task Scheduler helper: [`worker/windows_tasks.py`](../worker/windows_tasks.py)
