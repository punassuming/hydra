"""Windows backend: a per-user Task Scheduler task (``\\Hydra\\Daemon``) that starts at log on."""

from __future__ import annotations

import subprocess
from pathlib import Path

from worker import windows_tasks

from . import ServiceError, ServiceSpec, ServiceStatus

TASK_NAME = "\\Hydra\\Daemon"


def windowless_python(python: str) -> str:
    """``pythonw.exe`` next to ``python.exe`` runs without a console window; fall back to the given interpreter."""
    p = Path(python)
    if p.name.lower() == "python.exe":
        candidate = p.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return python


def build_command(spec: ServiceSpec) -> str:
    exe = windowless_python(spec.python)
    quoted = f'"{exe}"' if " " in exe else exe  # install_task splits on the first space, so quote a spaced path
    return " ".join([quoted, *spec.args()])


class WindowsTaskService:
    backend = "windows-task-scheduler"

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeError as exc:
            raise ServiceError(str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            detail = ((exc.stderr or "") + (exc.output or "")).strip().splitlines()
            raise ServiceError(f"Task Scheduler refused the request: {detail[-1] if detail else exc}") from exc

    def install(self, spec: ServiceSpec, start: bool = True, dry_run: bool = False) -> list[str]:
        command = build_command(spec)
        working_dir = spec.data_dir or str(Path.home())
        script = windows_tasks.build_register_script(
            TASK_NAME,
            command,
            working_dir=working_dir,
            schedule_type="ONLOGON",
            run_level="Limited",
            hidden=True,
            restart_count=999,
            description="Hydra job scheduler (lite edition). Managed by `hydra-ctl lite service`; do not edit manually.",
        )
        actions = [
            f"register scheduled task {TASK_NAME} (at log on, limited rights, hidden, restart on failure)",
            f"run: {command}",
        ]
        if dry_run:
            return actions + ["--- PowerShell ---", script.strip()]
        self._call(
            windows_tasks.install_task,
            TASK_NAME,
            command,
            working_dir=working_dir,
            schedule_type="ONLOGON",
            run_level="Limited",
            hidden=True,
            restart_count=999,
            description="Hydra job scheduler (lite edition). Managed by `hydra-ctl lite service`; do not edit manually.",
        )
        if start:
            self._call(windows_tasks.start_task, TASK_NAME)
            actions.append("started the task now")
        return actions

    def uninstall(self) -> list[str]:
        self._call(windows_tasks.stop_task, TASK_NAME)
        self._call(windows_tasks.remove_task, TASK_NAME)
        return [f"stopped and removed scheduled task {TASK_NAME} (data directory left untouched)"]

    def start(self) -> None:
        self._call(windows_tasks.start_task, TASK_NAME)

    def stop(self) -> None:
        self._call(windows_tasks.stop_task, TASK_NAME)

    def status(self) -> ServiceStatus:
        info = self._call(windows_tasks.task_info, TASK_NAME)
        if info is None:
            return ServiceStatus(self.backend, TASK_NAME, installed=False, running=False)
        return ServiceStatus(
            self.backend,
            TASK_NAME,
            installed=True,
            running=str(info.get("state")).lower() == "running",
            enabled=True,
            detail=info,
        )
