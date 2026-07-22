"""Runtime discovery and host configuration for worker executors."""

import logging
import os
import platform
import shutil
import subprocess
from typing import Optional


def _get_python_path() -> str:
    """Return the configured Python interpreter path, or an empty string."""
    return os.environ.get("HYDRA_PYTHON_PATH", "").strip()


def _get_shell_path() -> str:
    """Return the configured bash-compatible shell path, or an empty string."""
    return os.environ.get("HYDRA_SHELL_PATH", "").strip()


def _get_git_path() -> str:
    """Return the configured git binary path, or an empty string."""
    return os.environ.get("HYDRA_GIT_PATH", "").strip()


def _get_temp_dir() -> Optional[str]:
    """Return the configured executor scratch directory, if present."""
    value = os.environ.get("HYDRA_TEMP_DIR", "").strip()
    return value or None


def _resolve_shell(shell: str) -> str:
    """Resolve a requested shell to a host-appropriate executable."""
    requested = (shell or "bash").strip()
    normalized = requested.lower()
    if normalized == "bash":
        configured = _get_shell_path()
        if configured:
            return configured
        return shutil.which("bash") or ("bash" if platform.system().lower().startswith("win") else "/bin/bash")
    if normalized in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        candidates = ("powershell", "pwsh") if normalized.startswith("powershell") else ("pwsh", "powershell")
        return next((path for candidate in candidates if (path := shutil.which(candidate))), requested)
    if normalized in {"cmd", "cmd.exe"}:
        return shutil.which("cmd") or shutil.which("cmd.exe") or "cmd.exe"
    return shutil.which(requested) or requested


def _find_python() -> str:
    """Locate a working Python interpreter, honoring HYDRA_PYTHON_PATH."""
    configured = _get_python_path()
    if configured:
        try:
            subprocess.run([configured, "--version"], capture_output=True, timeout=5, check=True)
            return configured
        except (OSError, subprocess.SubprocessError):
            logging.warning(
                "HYDRA_PYTHON_PATH=%s is not a valid interpreter; falling back to PATH lookup",
                configured,
            )
    candidates = ("python", "python3") if platform.system().lower().startswith("win") else ("python3", "python")
    for interpreter in candidates:
        try:
            result = subprocess.run([interpreter, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return interpreter
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _detect_shells() -> list[str]:
    """Return shells that successfully execute a trivial command."""
    found: list[str] = []
    is_windows = platform.system().lower().startswith("win")
    shell_path = _get_shell_path()
    candidates = {
        "bash": [shell_path or ("/bin/bash" if not is_windows else "bash"), "-c", "exit 0"],
        "sh": ["/bin/sh", "-c", "exit 0"] if not is_windows else [],
        "cmd": ["cmd", "/c", "exit 0"] if is_windows else [],
        "powershell": ["powershell", "-Command", "exit 0"] if is_windows else [],
        "pwsh": ["pwsh", "-Command", "exit 0"],
    }
    for name, command in candidates.items():
        if not command:
            continue
        try:
            result = subprocess.run(command, capture_output=True, timeout=5)
            if result.returncode == 0:
                found.append(name)
        except (OSError, subprocess.SubprocessError):
            continue
    return found


def _detect_capabilities() -> list[str]:
    """Return executor types proven usable on this host."""
    capabilities: list[str] = []
    if _detect_shells():
        capabilities.extend(("shell", "external"))

    python_interpreter = _find_python()
    if python_interpreter:
        capabilities.append("python")

    for powershell in ("pwsh", "powershell"):
        try:
            result = subprocess.run([powershell, "-Command", "exit 0"], capture_output=True, timeout=5)
            if result.returncode == 0:
                capabilities.append("powershell")
                break
        except (OSError, subprocess.SubprocessError):
            continue

    if platform.system().lower().startswith("win"):
        capabilities.append("batch")

    if python_interpreter:
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            try:
                import pymongo  # noqa: F401
            except ImportError:
                pass
            else:
                capabilities.append("sql")
        else:
            capabilities.append("sql")

    capabilities.extend(("http", "sensor"))
    return capabilities
