"""Linux backend: a ``systemd --user`` unit (``hydra.service``)."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from pathlib import Path

from . import ServiceError, ServiceSpec, ServiceStatus

UNIT_NAME = "hydra.service"


def unit_path() -> Path:
    base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / UNIT_NAME


def _quote(arg: str) -> str:
    """Quote one ExecStart word per systemd.syntax: double quotes, backslash escapes, and ``%``/``$`` doubled."""
    arg = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{arg}"' if any(c in arg for c in " \t'\"\;") or arg == "" else arg


def render_unit(spec: ServiceSpec, working_dir: str) -> str:
    exec_start = " ".join(_quote(a) for a in [spec.python, *spec.args()])
    return f"""[Unit]
Description=Hydra job scheduler (lite edition)
Documentation=https://github.com/punassuming/Hydra
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={_quote(working_dir)}
Restart=on-failure
RestartSec=2
KillMode=control-group
TimeoutStopSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


class SystemdUserService:
    backend = "systemd-user"

    def __init__(self, enable_linger: bool = False):
        self.enable_linger = enable_linger

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        if shutil.which("systemctl") is None:
            raise ServiceError(
                "systemctl was not found: this system does not use systemd, so run `hydra-ctl lite daemon start` instead"
            )
        result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)  # noqa: S603,S607
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            hint = (
                " (is a systemd user session available? try logging in with a full session or `loginctl enable-linger`)"
                if "bus" in detail.lower()
                else ""
            )
            raise ServiceError(f"systemctl --user {' '.join(args)} failed: {detail}{hint}")
        return result

    def install(self, spec: ServiceSpec, start: bool = True, dry_run: bool = False) -> list[str]:
        from .. import config as config_module

        working_dir = spec.data_dir or str(config_module.load().data_dir)
        text = render_unit(spec, working_dir)
        path = unit_path()
        actions = [
            f"write {path}",
            "systemctl --user daemon-reload",
            f"systemctl --user enable{' --now' if start else ''} {UNIT_NAME}",
        ]
        if self.enable_linger:
            actions.append(f"loginctl enable-linger {getpass.getuser()}")
        if dry_run:
            return actions + ["--- unit ---", text.strip()]
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._systemctl("daemon-reload")
        self._systemctl("enable", *(["--now"] if start else []), UNIT_NAME)
        if start:  # re-installing over a running unit must pick up the new ExecStart
            self._systemctl("restart", UNIT_NAME)
        if self.enable_linger:
            result = subprocess.run(["loginctl", "enable-linger", getpass.getuser()], capture_output=True, text=True)  # noqa: S603,S607
            if result.returncode != 0:
                raise ServiceError(f"loginctl enable-linger failed: {(result.stderr or result.stdout).strip()}")
        else:
            actions.append("note: without `loginctl enable-linger` the service starts at your first login, not at boot")
        return actions

    def uninstall(self) -> list[str]:
        self._systemctl("disable", "--now", UNIT_NAME, check=False)
        path = unit_path()
        removed = path.exists()
        path.unlink(missing_ok=True)
        if shutil.which("systemctl"):
            self._systemctl("daemon-reload", check=False)
        return [
            f"disabled and stopped {UNIT_NAME}",
            f"{'removed' if removed else 'no unit file at'} {path} (data directory left untouched)",
        ]

    def start(self) -> None:
        self._systemctl("start", UNIT_NAME)

    def stop(self) -> None:
        self._systemctl("stop", UNIT_NAME)

    def status(self) -> ServiceStatus:
        installed = unit_path().exists()
        if not installed:
            return ServiceStatus(self.backend, UNIT_NAME, installed=False, running=False)
        active = self._systemctl("is-active", UNIT_NAME, check=False).stdout.strip()
        enabled = self._systemctl("is-enabled", UNIT_NAME, check=False).stdout.strip()
        return ServiceStatus(
            self.backend,
            UNIT_NAME,
            installed=True,
            running=active == "active",
            enabled=enabled == "enabled",
            detail={"active": active, "enabled": enabled, "unit": str(unit_path())},
        )
