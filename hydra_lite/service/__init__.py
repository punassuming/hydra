"""Run the daemon as a per-user background service (no administrator / root rights needed).

Windows: a Task Scheduler task that starts at the user's log on and is restarted on failure.
Linux: a ``systemd --user`` unit. Both launch ``python -m hydra_lite --service``; configuration stays in
``config.toml``, so the registration carries only what the user overrode on the command line.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

SERVICE_NAME = "Hydra"


class ServiceError(RuntimeError):
    """The service could not be managed; the message says what to do about it."""


@dataclass
class ServiceSpec:
    python: str = field(default_factory=lambda: sys.executable)
    data_dir: Optional[str] = None
    port: Optional[int] = None
    host: Optional[str] = None

    def args(self) -> list[str]:
        out = ["-m", "hydra_lite", "--service"]
        if self.host:
            out += ["--host", self.host]
        if self.port:
            out += ["--port", str(self.port)]
        if self.data_dir:
            out += ["--data-dir", str(self.data_dir)]
        return out


@dataclass
class ServiceStatus:
    backend: str
    name: str
    installed: bool
    running: bool
    enabled: bool = False
    detail: dict = field(default_factory=dict)


class ServiceManager(Protocol):
    backend: str

    def install(self, spec: ServiceSpec, start: bool = True, dry_run: bool = False) -> list[str]: ...

    def uninstall(self) -> list[str]: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def status(self) -> ServiceStatus: ...


def interpreter_warnings(python: str) -> list[str]:
    """Registering an interpreter that may disappear (temp dir, ``uv run`` ephemeral env, cache) breaks silently later."""
    path = str(Path(python).resolve()).lower()
    hints = (str(Path(tempfile.gettempdir()).resolve()).lower(), "/.cache/uv/", "\\uv\\cache\\", "/uv/archive-", "\\temp\\")
    if any(h in path for h in hints):
        return [
            f"the interpreter {python} looks temporary or cached; install Hydra with `uv tool install` or `pipx` and "
            "re-run `service install` (or pass --python) so the service keeps working"
        ]
    return []


def manager_for(platform: Optional[str] = None) -> ServiceManager:
    platform = platform or sys.platform
    if platform == "win32":
        from .windows import WindowsTaskService

        return WindowsTaskService()
    if platform.startswith("linux"):
        from .systemd_user import SystemdUserService

        return SystemdUserService()
    raise ServiceError(
        f"service install is not supported on {platform!r}; run `hydra-ctl lite daemon start` from your login items "
        "or launchd instead"
    )
