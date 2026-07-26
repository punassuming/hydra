"""Windows Worker Bootstrap for Hydra.

This module implements a lightweight watchdog/bootstrap process that keeps a
Hydra worker alive on Windows hosts.  A single Windows Task Scheduler entry
points to this bootstrap so that organisations can reduce many per-job Task
Scheduler items to just one per host.

Typical usage
-------------
Install the watchdog task (run once, as an administrator)::

    python -m worker bootstrap install

Remove the task::

    python -m worker bootstrap remove

Run the watchdog loop directly (useful for testing or manual invocation)::

    python -m worker bootstrap run

Validate that the environment is ready before installation::

    python -m worker bootstrap validate

All configuration is drawn from environment variables — see
:class:`BootstrapConfig` for the full list.
"""

from __future__ import annotations

import logging
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system().lower().startswith("win")


# ---------------------------------------------------------------------------
# .env file loader (no external dependencies)
# ---------------------------------------------------------------------------

def _load_env_file(path: Optional[str] = None) -> None:
    """Load key=value pairs from a .env file into os.environ.

    Variables already present in the environment are not overwritten, so
    explicit env vars always take precedence over the file.

    The file path is resolved in order:
    1. The *path* argument (if given).
    2. The ``HYDRA_ENV_FILE`` environment variable.
    3. ``.env`` in the current working directory.
    """
    candidate = path or os.environ.get("HYDRA_ENV_FILE") or ".env"
    try:
        env_path = Path(candidate)
        if not env_path.exists():
            return
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip optional surrounding quotes from the value.
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not load env file %r: %s", candidate, exc)

# ---------------------------------------------------------------------------
# Configuration model
# ---------------------------------------------------------------------------

@dataclass
class BootstrapConfig:
    """Configuration for the Windows worker bootstrap/watchdog.

    All fields can be overridden via environment variables.  The mapping from
    environment variable to attribute is documented per field.
    """

    # ------------------------------------------------------------------
    # Task Scheduler settings
    # ------------------------------------------------------------------

    task_name: str = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_TASK_NAME", "\\Hydra\\WorkerBootstrap"
    ))
    """Name of the Windows Task Scheduler task.

    Override with ``HYDRA_BOOTSTRAP_TASK_NAME``.
    Default: ``\\Hydra\\WorkerBootstrap``
    """

    schedule_type: str = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_SCHEDULE_TYPE", "ONSTART"
    ))
    """Task Scheduler trigger type: ``ONSTART`` (system start-up) or ``MINUTE``.

    Override with ``HYDRA_BOOTSTRAP_SCHEDULE_TYPE``.
    Default: ``ONSTART``
    """

    interval_minutes: int = field(default_factory=lambda: int(
        os.environ.get("HYDRA_BOOTSTRAP_INTERVAL_MINUTES", "5")
    ))
    """Repetition interval in minutes when *schedule_type* is ``MINUTE``.

    Override with ``HYDRA_BOOTSTRAP_INTERVAL_MINUTES``.
    Default: ``5``
    """

    run_as_system: bool = field(default_factory=lambda: (
        os.environ.get("HYDRA_BOOTSTRAP_RUN_AS_SYSTEM", "false").lower() in ("1", "true", "yes")
    ))
    """Run the scheduled task as the SYSTEM account.

    Override with ``HYDRA_BOOTSTRAP_RUN_AS_SYSTEM`` (``true``/``false``).
    Default: ``false``
    """

    # ------------------------------------------------------------------
    # Watchdog settings
    # ------------------------------------------------------------------

    watchdog_interval_seconds: int = field(default_factory=lambda: int(
        os.environ.get("HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL", "30")
    ))
    """Seconds between watchdog health checks.

    Override with ``HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL``.
    Default: ``30``
    """

    lock_file: str = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_LOCK_FILE",
        str(Path(os.environ.get("TEMP", os.environ.get("TMP", "C:\\Windows\\Temp"))) / "hydra_bootstrap.lock")
    ))
    """Path to the PID lock file used to prevent duplicate watchdog processes.

    Override with ``HYDRA_BOOTSTRAP_LOCK_FILE``.
    Default: ``%TEMP%\\hydra_bootstrap.lock``
    """

    # ------------------------------------------------------------------
    # Worker command settings
    # ------------------------------------------------------------------

    worker_command: str = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_WORKER_COMMAND",
        f"{sys.executable} -m worker"
    ))
    """Command used to launch the Hydra worker process.

    Override with ``HYDRA_BOOTSTRAP_WORKER_COMMAND``.
    Default: ``<current python> -m worker``
    """

    working_dir: Optional[str] = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_WORKING_DIR"
    ))
    """Working directory for the worker process.

    Override with ``HYDRA_BOOTSTRAP_WORKING_DIR``.
    Default: current working directory at install time.
    """

    log_file: Optional[str] = field(default_factory=lambda: os.environ.get(
        "HYDRA_BOOTSTRAP_LOG_FILE"
    ))
    """Path to a file where worker stdout/stderr will be redirected.

    Override with ``HYDRA_BOOTSTRAP_LOG_FILE``.
    Default: ``None`` (inherits parent stdout/stderr).
    """

    # ------------------------------------------------------------------
    # Required env-var checks (validated before install/run)
    # ------------------------------------------------------------------

    domain: str = field(default_factory=lambda: (os.environ.get("DOMAIN") or "prod").strip())
    api_token: str = field(default_factory=lambda: (os.environ.get("API_TOKEN") or "").strip())
    redis_url: str = field(default_factory=lambda: (os.environ.get("REDIS_URL") or "").strip())

    @classmethod
    def from_env(cls) -> "BootstrapConfig":
        """Construct a :class:`BootstrapConfig` from the current environment."""
        return cls()

    def validate(self) -> list[str]:
        """Return a list of validation error messages (empty means valid)."""
        errors: list[str] = []
        if not self.api_token:
            errors.append("API_TOKEN is not set. The worker requires a domain token.")
        if not self.redis_url:
            errors.append("REDIS_URL is not set. The worker requires a Redis connection URL.")
        if not self.worker_command.strip():
            errors.append("HYDRA_BOOTSTRAP_WORKER_COMMAND is empty.")
        if self.watchdog_interval_seconds < 5:
            errors.append(
                f"HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL={self.watchdog_interval_seconds} is too small (minimum 5s)."
            )
        if self.interval_minutes < 1:
            errors.append(
                f"HYDRA_BOOTSTRAP_INTERVAL_MINUTES={self.interval_minutes} must be >= 1."
            )
        return errors


# ---------------------------------------------------------------------------
# Lock / PID helpers
# ---------------------------------------------------------------------------

def _read_lock_pid(lock_path: str) -> Optional[int]:
    """Return the PID recorded in *lock_path*, or ``None`` if unreadable."""
    try:
        content = Path(lock_path).read_text(encoding="utf-8").strip()
        return int(content) if content else None
    except Exception:
        return None


def _write_lock(lock_path: str, pid: int) -> None:
    """Write *pid* to *lock_path*, creating parent directories as needed."""
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    Path(lock_path).write_text(str(pid), encoding="utf-8")


def _remove_lock(lock_path: str) -> None:
    """Delete *lock_path* if it exists."""
    try:
        Path(lock_path).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to remove lock file %r: %s", lock_path, exc)


def _is_pid_alive(pid: int) -> bool:
    """Return ``True`` if a process with *pid* is currently running."""
    if _IS_WINDOWS:
        try:
            # Avoid shelling out to tasklist: it is not guaranteed to be on
            # PATH for a service account, while OpenProcess is always present.
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            # A protected process can deny inspection but still holds the PID.
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def acquire_bootstrap_lock(lock_path: str) -> bool:
    """Attempt to acquire the bootstrap lock.

    Returns ``True`` if the lock was acquired (this process is now the sole
    watchdog), ``False`` if another watchdog process already holds the lock.
    """
    existing_pid = _read_lock_pid(lock_path)
    if existing_pid is not None and existing_pid != os.getpid():
        if _is_pid_alive(existing_pid):
            logger.info(
                "Another bootstrap watchdog is already running (PID %d). Exiting.", existing_pid
            )
            return False
        else:
            logger.info("Stale lock file found (PID %d no longer alive). Replacing.", existing_pid)

    _write_lock(lock_path, os.getpid())
    logger.debug("Bootstrap lock acquired (PID %d) at %r.", os.getpid(), lock_path)
    return True


# ---------------------------------------------------------------------------
# Worker process management
# ---------------------------------------------------------------------------

def _build_worker_env() -> dict:
    """Return an environment dict for the worker process.

    Starts from the current process environment and passes through all
    HYDRA_* / DOMAIN / API_TOKEN / REDIS_* variables so the worker inherits
    them correctly.

    Sets ``DEPLOYMENT_TYPE=scheduler`` if not already present so that workers
    launched by the bootstrap are identified correctly in the Hydra UI.
    """
    env = os.environ.copy()
    env.setdefault("DEPLOYMENT_TYPE", "scheduler")
    return env


def _start_worker(config: BootstrapConfig) -> Optional[subprocess.Popen]:
    """Launch the Hydra worker process described by *config*.

    Returns the :class:`subprocess.Popen` object, or ``None`` if the launch
    fails.
    """
    cmd_parts = config.worker_command.split()
    cwd = config.working_dir or os.getcwd()
    env = _build_worker_env()

    log_fh = None
    if config.log_file:
        try:
            Path(config.log_file).parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(config.log_file, "a", encoding="utf-8")  # noqa: WPS515
        except OSError as exc:
            logger.warning("Cannot open log file %r: %s — falling back to inherited stdio.", config.log_file, exc)
            log_fh = None

    stdout = log_fh if log_fh else None
    stderr = log_fh if log_fh else None

    try:
        proc = subprocess.Popen(
            cmd_parts,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
        logger.info("Started worker process PID=%d (command: %s).", proc.pid, config.worker_command)
        return proc
    except Exception as exc:
        logger.error("Failed to start worker process: %s", exc)
        if log_fh is not None:
            log_fh.close()
        return None


def _is_worker_alive(proc: Optional[subprocess.Popen]) -> bool:
    """Return ``True`` if *proc* is still running."""
    if proc is None:
        return False
    return proc.poll() is None


# ---------------------------------------------------------------------------
# Watchdog loop
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, _frame) -> None:  # type: ignore[type-arg]
    global _shutdown_requested
    logger.info("Bootstrap watchdog received signal %d; shutting down.", signum)
    _shutdown_requested = True


def run_watchdog(config: BootstrapConfig) -> int:
    """Run the watchdog loop until interrupted.

    The loop:
    1. Acquires a PID lock to prevent duplicate watchdog processes.
    2. Starts the worker if it is not already running.
    3. Sleeps for *config.watchdog_interval_seconds*.
    4. Checks whether the worker is still alive; restarts if not.
    5. Exits cleanly on SIGTERM / SIGINT (and removes the lock file).

    If the worker fails to start repeatedly, an exponential backoff (up to
    5 minutes) is applied between restart attempts to prevent tight restart
    loops from consuming resources.

    Returns
    -------
    int
        Exit code (0 = clean shutdown, 1 = lock already held by another process).
    """
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not acquire_bootstrap_lock(config.lock_file):
        return 1

    worker_proc: Optional[subprocess.Popen] = None
    consecutive_failures = 0
    _MAX_BACKOFF_SECONDS = 300  # 5 minutes

    try:
        while not _shutdown_requested:
            if not _is_worker_alive(worker_proc):
                if worker_proc is not None:
                    rc = worker_proc.returncode
                    logger.warning("Worker process PID=%d exited with code %s; restarting.", worker_proc.pid, rc)
                worker_proc = _start_worker(config)
                if worker_proc is None:
                    consecutive_failures += 1
                    backoff = min(config.watchdog_interval_seconds * (2 ** (consecutive_failures - 1)), _MAX_BACKOFF_SECONDS)
                    logger.warning(
                        "Worker failed to start (attempt %d); backing off %.0f s.",
                        consecutive_failures,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                else:
                    consecutive_failures = 0

            # Refresh lock file with current PID (guards against stale-lock detection
            # by a concurrently starting instance of this bootstrap).
            _write_lock(config.lock_file, os.getpid())

            time.sleep(config.watchdog_interval_seconds)
    finally:
        _remove_lock(config.lock_file)
        if worker_proc is not None and _is_worker_alive(worker_proc):
            logger.info("Stopping worker process PID=%d.", worker_proc.pid)
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logger.warning("Worker did not stop within 15 s; killing.")
                worker_proc.kill()

    logger.info("Bootstrap watchdog exited cleanly.")
    return 0


# ---------------------------------------------------------------------------
# Public action functions
# ---------------------------------------------------------------------------

def action_validate(config: BootstrapConfig) -> int:
    """Print validation results and return 0 if valid, 1 otherwise."""
    errors = config.validate()
    if errors:
        print("Bootstrap configuration errors:", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1
    print("Bootstrap configuration is valid.")
    print(f"  task_name             : {config.task_name}")
    print(f"  schedule_type         : {config.schedule_type}")
    if config.schedule_type == "MINUTE":
        print(f"  interval_minutes      : {config.interval_minutes}")
    print(f"  worker_command        : {config.worker_command}")
    print(f"  working_dir           : {config.working_dir or os.getcwd()!r} (effective)")
    print(f"  lock_file             : {config.lock_file}")
    print(f"  watchdog_interval (s) : {config.watchdog_interval_seconds}")
    if config.log_file:
        print(f"  log_file              : {config.log_file}")
    print(f"  domain                : {config.domain}")
    return 0


def action_install(config: BootstrapConfig) -> int:
    """Install (or update) the Windows Task Scheduler bootstrap task.

    Raises ``RuntimeError`` on non-Windows platforms.
    Returns 0 on success, 1 on validation error.
    """
    if not _IS_WINDOWS:
        raise RuntimeError(
            "Task Scheduler installation is only supported on Windows. "
            f"Current platform: {platform.system()!r}."
        )

    errors = config.validate()
    if errors:
        print("Cannot install: configuration is invalid.", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    from .windows_tasks import install_task

    # Build the full bootstrap run command that the scheduled task will call.
    bootstrap_command = f"{sys.executable} -m worker bootstrap run"

    effective_working_dir = config.working_dir or os.getcwd()

    install_task(
        task_name=config.task_name,
        command=bootstrap_command,
        working_dir=effective_working_dir,
        schedule_type=config.schedule_type,
        interval_minutes=config.interval_minutes,
        run_as_system=config.run_as_system,
        description=(
            "Hydra worker bootstrap/watchdog. "
            f"Domain: {config.domain}. "
            "Managed by Hydra — do not edit manually."
        ),
    )

    print(f"Task {config.task_name!r} installed successfully.")
    print("The task will launch the Hydra worker watchdog on the next trigger.")
    print(f"  Trigger        : {config.schedule_type}")
    print(f"  Worker command : {config.worker_command}")
    return 0


def action_remove(config: BootstrapConfig) -> int:
    """Remove the Windows Task Scheduler bootstrap task.

    Raises ``RuntimeError`` on non-Windows platforms.
    Returns 0 on success.
    """
    if not _IS_WINDOWS:
        raise RuntimeError(
            "Task Scheduler removal is only supported on Windows. "
            f"Current platform: {platform.system()!r}."
        )

    from .windows_tasks import remove_task

    remove_task(config.task_name)
    print(f"Task {config.task_name!r} removed (or was not present).")
    return 0


def action_run(config: BootstrapConfig) -> int:
    """Run the watchdog loop (blocking).

    This is the entry point that the scheduled task calls.  Returns the
    watchdog exit code.
    """
    errors = config.validate()
    if errors:
        print("Cannot run watchdog: configuration is invalid.", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting Hydra worker bootstrap watchdog.")
    logger.info("Worker command: %s", config.worker_command)
    logger.info("Lock file     : %s", config.lock_file)

    return run_watchdog(config)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI dispatcher for ``python -m worker bootstrap <subcommand>``.

    Subcommands:
    - ``install``   Install (or update) the scheduled task.
    - ``remove``    Remove the scheduled task.
    - ``run``       Run the watchdog loop (blocking).
    - ``validate``  Validate configuration and print a summary.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m worker bootstrap",
        description="Hydra worker bootstrap — manage the Windows Task Scheduler watchdog task.",
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="subcommand")
    sub.required = True

    sub.add_parser("install", help="Install or update the Task Scheduler bootstrap task.")
    sub.add_parser("remove", help="Remove the Task Scheduler bootstrap task.")
    sub.add_parser("run", help="Run the watchdog loop (blocking; called by the scheduled task).")
    sub.add_parser("validate", help="Validate configuration and print a summary.")

    args = parser.parse_args(argv)
    _load_env_file()
    config = BootstrapConfig.from_env()

    actions = {
        "install": action_install,
        "remove": action_remove,
        "run": action_run,
        "validate": action_validate,
    }
    return actions[args.subcommand](config)
