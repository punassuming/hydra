# Windows Worker Deployment Guide

This guide explains how to keep a Hydra worker running on a Windows host
across reboots and crashes. Two launch mechanisms are covered — pick one:

| | Task Scheduler (built-in) | Windows Service (NSSM) |
|---|---|---|
| Extra tooling required | None — ships with Windows | [NSSM](https://nssm.cc/) (or another service wrapper) |
| Visible in `services.msc` / `sc query` | No | Yes |
| Restart-on-crash | Handled by the bootstrap watchdog | Handled by NSSM/SCM **and** the watchdog (layered) |
| Starts before any user logs on | Only with `HYDRA_BOOTSTRAP_RUN_AS_SYSTEM=true` or a "run whether user is logged on or not" trigger | Yes, by default (services start at boot) |
| Managed by monitoring/CMDB tools that watch Windows Services | No | Yes |
| Environment locked down by policy (Task Scheduler restricted) | May be blocked | Usually unaffected |
| Setup effort | Lower (nothing to install) | Slightly higher (install NSSM once) |

Both mechanisms launch the **same** underlying command
(`python -m worker bootstrap run`, the watchdog described below) — they only
differ in what supervises that command. The **Runtime directory setup** and
**Environment Variables** sections below apply to both; jump to
[Launch mechanism 1: Task Scheduler](#launch-mechanism-1-task-scheduler-built-in)
or [Launch mechanism 2: Windows Service (NSSM)](#launch-mechanism-2-windows-service-nssm)
once your `.env` is in place.

## Overview

Instead of creating many per-job Task Scheduler entries or per-job services,
the Windows Worker Bootstrap lets you:

1. Register **one** Task Scheduler task, or **one** Windows Service, per host
   that launches a lightweight watchdog process on start-up.
2. The watchdog keeps the Hydra worker process alive, restarting it if it
   exits unexpectedly.
3. All actual job scheduling is centralised in the Hydra scheduler — the
   Task Scheduler entry / Windows Service is only responsible for worker
   lifecycle.

```
Windows Task Scheduler                    OR    Windows Service (NSSM)
  └─ Hydra\WorkerBootstrap                         └─ HydraWorker (SCM-managed)
       └─ python -m worker bootstrap run                └─ python -m worker bootstrap run
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
| Administrator rights | Required only for the install step (to create the scheduled task or service) |
| [NSSM](https://nssm.cc/) | Only if using **Launch mechanism 2: Windows Service** instead of Task Scheduler |

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

## Launch mechanism 1: Task Scheduler (built-in)

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

## Launch mechanism 2: Windows Service (NSSM)

Prefer this path if you want the worker to show up in `services.msc`/`sc
query`, be managed by the same tooling you use for other Windows services, or
your environment restricts Task Scheduler. Hydra does not require a Python
service framework (no `pywin32` dependency) — instead, wrap the existing
watchdog command with [NSSM](https://nssm.cc/), a small, widely used utility
that runs any executable as a proper Windows Service.

This section assumes the same runtime directory and `.env` file from
**Runtime directory setup** above (`C:\hydra-worker\`).

### Install NSSM

Download NSSM from [nssm.cc](https://nssm.cc/download) (or install via a
package manager, e.g. `choco install nssm` / `winget install NSSM.NSSM`) and
place `nssm.exe` somewhere on `PATH`, e.g. `C:\tools\nssm\nssm.exe`.

### Register the service

Run in an **elevated (administrator)** PowerShell session:

```powershell
nssm install HydraWorker "C:\hydra-worker\.venv\Scripts\python.exe" "-m worker bootstrap run"
nssm set HydraWorker AppDirectory C:\hydra-worker
nssm set HydraWorker DisplayName "Hydra Worker"
nssm set HydraWorker Description "Hydra job scheduler worker (watchdog-supervised)"
nssm set HydraWorker Start SERVICE_AUTO_START
```

`bootstrap run` is the same watchdog command used by the Task Scheduler path
— NSSM just replaces Task Scheduler as the thing that launches and supervises
it. The watchdog still reads credentials from `C:\hydra-worker\.env`
automatically, so no environment variables need to be set on the service
itself. If you'd rather skip the watchdog layer and let NSSM alone supervise
the worker process directly (simpler, but no exponential-backoff restart
delay), point the service at `-m worker` instead of `-m worker bootstrap run`.

### Configure stdout/stderr logging

NSSM can capture the process's console output directly, which is often more
convenient than `HYDRA_BOOTSTRAP_LOG_FILE`:

```powershell
nssm set HydraWorker AppStdout C:\hydra-worker\logs\worker.log
nssm set HydraWorker AppStderr C:\hydra-worker\logs\worker.log
nssm set HydraWorker AppRotateFiles 1
nssm set HydraWorker AppRotateBytes 10485760
```

### Configure restart-on-failure

The bootstrap watchdog already restarts a crashed `worker` subprocess with
backoff. Layering SCM-level recovery on top covers the (rarer) case where the
watchdog process itself dies:

```powershell
nssm set HydraWorker AppExit Default Restart
nssm set HydraWorker AppRestartDelay 5000
```

### Run under a dedicated service account

By default NSSM runs the service as `LocalSystem`. To run as a dedicated
service account instead (recommended — see **Service account** below):

```powershell
nssm set HydraWorker ObjectName "DOMAIN\svc_hydra" "the-account-password"
```

### Start / stop / status / remove

```powershell
nssm start HydraWorker
nssm status HydraWorker      # SERVICE_RUNNING / SERVICE_STOPPED / ...
nssm stop HydraWorker
nssm remove HydraWorker confirm
```

Equivalent native commands also work once the service is registered:
`sc start HydraWorker`, `sc stop HydraWorker`, `sc query HydraWorker`, and the
service appears in `services.msc` as "Hydra Worker".

> **Note:** `nssm remove` does **not** stop a currently running worker
> subprocess spawned by the watchdog — stop the service first (`nssm stop
> HydraWorker`), which sends a stop signal the watchdog's `SIGTERM`/`SIGINT`
> handler picks up to shut down the worker cleanly before the service exits.

---

## Complete example (Task Scheduler, production)

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

## Complete example (Windows Service, production)

Same runtime setup as above, but registered as an NSSM-managed service
instead of a Task Scheduler entry:

```powershell
# ── Hydra Worker — Windows Service setup (via NSSM) ────────────────────────

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
WORKER_TAGS=windows,prod,batch
MAX_CONCURRENCY=4
PYTHONUNBUFFERED=1
"@ | Set-Content C:\hydra-worker\.env

# 3. Validate before registering the service.
.\.venv\Scripts\python.exe -m worker bootstrap validate
if ($LASTEXITCODE -ne 0) { exit 1 }

# 4. Register the service (requires elevated shell, requires nssm.exe on PATH).
nssm install HydraWorker "C:\hydra-worker\.venv\Scripts\python.exe" "-m worker bootstrap run"
nssm set HydraWorker AppDirectory C:\hydra-worker
nssm set HydraWorker DisplayName "Hydra Worker"
nssm set HydraWorker Description "Hydra job scheduler worker (watchdog-supervised)"
nssm set HydraWorker Start SERVICE_AUTO_START
nssm set HydraWorker AppStdout C:\hydra-worker\logs\worker.log
nssm set HydraWorker AppStderr C:\hydra-worker\logs\worker.log
nssm set HydraWorker AppRotateFiles 1
nssm set HydraWorker AppRotateBytes 10485760
nssm set HydraWorker AppExit Default Restart
nssm set HydraWorker AppRestartDelay 5000

# 5. Start it.
nssm start HydraWorker
nssm status HydraWorker
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
- The `install` command (or `nssm install`) requires administrator rights to
  create the Task Scheduler entry / service, but the watchdog and worker
  processes themselves do **not** need to run elevated.

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
to rotate the file. If you're running as an NSSM service instead, prefer
NSSM's own rotation (`AppRotateFiles`/`AppRotateBytes`/`AppRotateSeconds`,
shown in the Windows Service example above) over `HYDRA_BOOTSTRAP_LOG_FILE` —
don't set both to the same path, or two writers will contend for the file.

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
2. Ensure only one Task Scheduler task (or one NSSM service) is configured
   for the host — running both mechanisms for the same worker at once will
   start two watchdogs.
3. Delete the stale lock file manually if the watchdog process has exited:
   ```powershell
   Remove-Item $env:TEMP\hydra_bootstrap.lock -ErrorAction SilentlyContinue
   ```

### Service shows "Starting" then stops immediately (NSSM)

1. Run the exact command NSSM launches, interactively, to see the real error:
   `C:\hydra-worker\.venv\Scripts\python.exe -m worker bootstrap run`.
2. Check `nssm get HydraWorker AppDirectory` matches `C:\hydra-worker` — a
   wrong working directory means `.env` won't be found.
3. Check the NSSM-captured log (`AppStdout`/`AppStderr`) or, if unset, the
   Windows Event Log (`eventvwr.msc` → Windows Logs → Application, source
   `nssm`) for the process's exit code.
4. Confirm the service account (`nssm get HydraWorker ObjectName`) has read
   access to the venv and `.env`, and network access to Redis.

### "The service did not respond to the start or control request in a timely fashion"

NSSM waits a fixed startup window before reporting failure. This usually
means the Python process itself errored before entering the watchdog loop —
check `AppStdout`/`AppStderr` first; it's rarely an NSSM configuration issue.

---

## Reference

- [Task Scheduler documentation (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page)
- [`schtasks` command reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks)
- [NSSM — the Non-Sucking Service Manager](https://nssm.cc/)
- [NSSM usage reference](https://nssm.cc/usage)
- Hydra worker configuration: [`worker/config.py`](../worker/config.py)
- Bootstrap source: [`worker/bootstrap.py`](../worker/bootstrap.py)
- Task Scheduler helper: [`worker/windows_tasks.py`](../worker/windows_tasks.py)
