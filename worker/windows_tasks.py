"""Windows Task Scheduler helpers for Hydra worker bootstrap.

Uses the ``schtasks`` command-line tool which ships with all modern Windows
editions.  Every public function raises ``RuntimeError`` when called on a
non-Windows platform so that the rest of the bootstrap module can fail fast
with a clear message.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system().lower().startswith("win")

# Maximum length of a Task Scheduler task name (documented limit is 238 chars,
# but we cap earlier for sanity).
_TASK_NAME_MAX_LEN = 200


def _require_windows() -> None:
    """Raise RuntimeError if not running on Windows."""
    if not _IS_WINDOWS:
        raise RuntimeError(
            "Windows Task Scheduler management is only supported on Windows. "
            f"Current platform: {platform.system()!r}. "
            "To run a Hydra worker on Linux/macOS use a systemd service, "
            "launchd plist, or a simple process supervisor instead."
        )


def _quote_arg(value: str) -> str:
    """Return *value* safely quoted for use inside a schtasks /TR argument.

    schtasks /TR receives the full command string as a single argument.  Any
    double-quotes inside the command must be escaped as two consecutive
    double-quotes so that cmd.exe passes them through correctly.
    """
    return value.replace('"', '""')


def build_schtasks_create_command(
    task_name: str,
    command: str,
    working_dir: Optional[str],
    schedule_type: str,
    interval_minutes: int,
    run_as_system: bool,
    description: str,
) -> List[str]:
    """Build the schtasks /Create argument list.

    Parameters
    ----------
    task_name:
        Name of the scheduled task (may include a folder prefix like
        ``\\Hydra\\worker-prod``).
    command:
        Full command string that the task will execute (e.g. the Python
        interpreter followed by bootstrap arguments).
    working_dir:
        Working directory for the task, or ``None`` to use the system default.
    schedule_type:
        One of ``"ONSTART"``, ``"ONCE"``, or ``"MINUTE"``.  Bootstrap tasks
        use ``"ONSTART"`` for the primary trigger and ``"MINUTE"`` for the
        periodic watchdog check.
    interval_minutes:
        For ``"MINUTE"`` schedule, the repetition interval in minutes.
    run_as_system:
        When ``True``, run as ``SYSTEM`` (requires administrator privileges on
        the installing account).
    description:
        Human-readable description stored in the Task Scheduler entry.

    Returns
    -------
    List[str]
        Argument list suitable for ``subprocess.run``.
    """
    quoted_cmd = f'"{_quote_arg(command)}"'

    args: List[str] = [
        "schtasks",
        "/Create",
        "/F",  # Force overwrite if task already exists (idempotent)
        "/TN", task_name,
        "/TR", quoted_cmd,
        "/SC", schedule_type,
        "/RL", "HIGHEST",
    ]

    if schedule_type == "MINUTE":
        args += ["/MO", str(interval_minutes)]

    if run_as_system:
        args += ["/RU", "SYSTEM"]

    # Note: schtasks /Create does not support a working-directory flag.
    # The caller embeds a `cd /d <dir> &&` prefix in the command instead so
    # that the working directory is honoured at execution time.

    # schtasks /Create does not support a /Description flag from the command
    # line; descriptions can only be set via XML import.  We log it for
    # operational reference but do not inject it into the command.
    logger.debug("Task description (not persisted via schtasks CLI): %s", description)

    return args


def build_schtasks_delete_command(task_name: str) -> List[str]:
    """Return the schtasks /Delete argument list for *task_name*."""
    return ["schtasks", "/Delete", "/F", "/TN", task_name]


def build_schtasks_query_command(task_name: str) -> List[str]:
    """Return the schtasks /Query argument list for *task_name*."""
    return ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"]


def run_schtasks(args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Execute a schtasks command and return the completed process.

    The command is always run with ``shell=False`` to avoid injection risks.
    stdout/stderr are captured as UTF-8 text (with ``errors="replace"``).

    Raises
    ------
    RuntimeError
        On non-Windows platforms.
    subprocess.CalledProcessError
        When the process exits with a non-zero return code.
    """
    _require_windows()
    logger.debug("Running schtasks: %s", args)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _ps_escape(value: str) -> str:
    """Escape a string for safe embedding inside a PowerShell single-quoted string."""
    # In PowerShell single-quoted strings, a literal ' is written as ''.
    return value.replace("'", "''")


def install_task(
    task_name: str,
    command: str,
    *,
    working_dir: Optional[str] = None,
    schedule_type: str = "ONSTART",
    interval_minutes: int = 5,
    run_as_system: bool = False,
    description: str = "Hydra worker watchdog/bootstrap",
) -> None:
    """Create or update a Windows scheduled task via PowerShell Register-ScheduledTask.

    Using Register-ScheduledTask (rather than schtasks /Create /TR) avoids the
    double-quoting ambiguity in schtasks /TR, where cmd.exe is treated as the
    program name instead of just an executable, and the working directory can be
    set directly on the action without embedding a ``cd /d`` wrapper.

    Calling this function multiple times is safe — ``-Force`` overwrites any
    existing task of the same name.

    Parameters
    ----------
    task_name:
        Name of the scheduled task (may include a folder prefix like
        ``\\Hydra\\worker-prod``).
    command:
        Full command string for the task action (e.g.
        ``C:\\Python311\\python.exe -m worker bootstrap run``).  The first
        space-separated token is used as the executable; the remainder as
        arguments.
    working_dir:
        Working directory for the task action.  Passed directly to the
        ``New-ScheduledTaskAction -WorkingDirectory`` parameter; no shell
        wrapping required.
    schedule_type:
        ``"ONSTART"`` (run at system start-up) or ``"MINUTE"`` (periodic).
    interval_minutes:
        Interval for ``"MINUTE"`` schedule type.
    run_as_system:
        Run as SYSTEM account.  Requires the installing user to have admin
        privileges.
    description:
        Human-readable description (stored in the task definition).

    Raises
    ------
    RuntimeError
        On non-Windows platforms.
    subprocess.CalledProcessError
        When PowerShell exits with a non-zero return code.
    """
    _require_windows()

    # Split command into executable + arguments (first token vs the rest).
    parts = command.split(None, 1)
    executable = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""

    # Build the PowerShell trigger expression.
    if schedule_type == "ONSTART":
        trigger_expr = "New-ScheduledTaskTrigger -AtStartup"
    elif schedule_type == "MINUTE":
        trigger_expr = (
            f"New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes {interval_minutes}) "
            "-Once -At '00:00'"
        )
    else:
        raise ValueError(f"Unsupported schedule_type {schedule_type!r}; expected 'ONSTART' or 'MINUTE'.")

    wd_line = (
        f"-WorkingDirectory '{_ps_escape(working_dir)}' "
        if working_dir
        else ""
    )
    run_level = "Highest"
    user_id = "SYSTEM" if run_as_system else "$env:USERNAME"
    user_line = (
        f"New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel {run_level} -LogonType ServiceAccount"
        if run_as_system
        else f"New-ScheduledTaskPrincipal -UserId {user_id} -RunLevel {run_level} -LogonType Interactive"
    )

    ps_script = f"""
$action  = New-ScheduledTaskAction `
    -Execute '{_ps_escape(executable)}' `
    -Argument '{_ps_escape(arguments)}' `
    {wd_line}
$trigger   = {trigger_expr}
$principal = {user_line}
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask `
    -TaskName '{_ps_escape(task_name)}' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description '{_ps_escape(description)}' `
    -Force | Out-Null
Write-Host "Task '{_ps_escape(task_name)}' registered successfully."
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["powershell", "..."],
            output=result.stdout,
            stderr=result.stderr,
        )
    logger.info("Task %r installed/updated successfully.", task_name)
    if result.stdout:
        logger.debug("Register-ScheduledTask output: %s", result.stdout.strip())


def remove_task(task_name: str) -> None:
    """Delete a Windows scheduled task by name.

    If the task does not exist the function logs a warning and returns without
    raising an exception (idempotent removal).

    Raises
    ------
    RuntimeError
        On non-Windows platforms.
    subprocess.CalledProcessError
        When schtasks exits with a non-zero return code for reasons other than
        "task not found".
    """
    _require_windows()
    try:
        run_schtasks(build_schtasks_delete_command(task_name))
        logger.info("Task %r removed successfully.", task_name)
    except subprocess.CalledProcessError as exc:
        # schtasks returns exit code 1 with "ERROR: The system cannot find the
        # file specified." when the task does not exist.
        combined = (exc.output or "") + (exc.stderr or "")
        if "cannot find" in combined.lower() or "does not exist" in combined.lower():
            logger.warning("Task %r not found; nothing to remove.", task_name)
        else:
            raise


def task_exists(task_name: str) -> bool:
    """Return ``True`` if a Windows scheduled task with *task_name* exists.

    Raises
    ------
    RuntimeError
        On non-Windows platforms.
    """
    _require_windows()
    try:
        run_schtasks(build_schtasks_query_command(task_name))
        return True
    except subprocess.CalledProcessError:
        return False
