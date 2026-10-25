"""Service install: generated registrations are tested everywhere; real Task Scheduler runs only on Windows CI."""

import os
import stat
import subprocess
import sys

import pytest

from cli.__main__ import main
from hydra_lite import service
from hydra_lite.service import ServiceError, ServiceSpec, interpreter_warnings, systemd_user, windows
from worker import windows_tasks


def test_spec_args_carry_only_overrides():
    assert ServiceSpec(python="py").args() == ["-m", "hydra_lite", "--service"]
    assert ServiceSpec(python="py", port=9000, host="127.0.0.1", data_dir="/d x").args() == [
        "-m",
        "hydra_lite",
        "--service",
        "--host",
        "127.0.0.1",
        "--port",
        "9000",
        "--data-dir",
        "/d x",
    ]


def test_interpreter_warnings_flag_ephemeral_locations(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))  # pytest's tmp_path need not live under the OS temp dir
    fake = tmp_path / "venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    assert interpreter_warnings(str(fake))  # under the temp dir
    assert not interpreter_warnings(sys.executable) or "temporary" in interpreter_warnings(sys.executable)[0]


def test_unsupported_platform_is_a_clear_error():
    with pytest.raises(ServiceError, match="not supported"):
        service.manager_for("darwin")


# ------------------------------------------------------------------------------ Windows (generated text)


def test_windows_register_script_is_per_user_at_logon_and_needs_no_admin():
    script = windows_tasks.build_register_script(
        "\\Hydra\\Daemon",
        "C:\\Py\\pythonw.exe -m hydra_lite --service",
        working_dir="C:\\Data",
        schedule_type="ONLOGON",
        run_level="Limited",
        hidden=True,
        restart_count=999,
    )
    assert "New-ScheduledTaskTrigger -AtLogOn -User" in script
    assert "-RunLevel Limited" in script and "Highest" not in script
    assert "-RestartCount 999" in script and "-Hidden" in script and "-MultipleInstances IgnoreNew" in script
    assert "-Execute 'C:\\Py\\pythonw.exe'" in script and "-WorkingDirectory 'C:\\Data'" in script
    assert "SYSTEM" not in script


def test_existing_bootstrap_registration_is_unchanged():
    script = windows_tasks.build_register_script(
        "\\Hydra\\WorkerBootstrap", "python -m worker bootstrap run", working_dir="C:\\w"
    )
    assert "-AtStartup" in script and "-RunLevel Highest" in script and "-RestartCount 3 " in script
    assert "-Hidden" not in script and "StartWhenAvailable" not in script


def test_windows_command_quotes_a_spaced_interpreter_and_prefers_pythonw(tmp_path):
    d = tmp_path / "Program Files" / "Py"
    d.mkdir(parents=True)
    (d / "python.exe").write_text("")
    (d / "pythonw.exe").write_text("")
    cmd = windows.build_command(ServiceSpec(python=str(d / "python.exe")))
    assert cmd.startswith(f'"{d / "pythonw.exe"}" -m hydra_lite --service')
    assert windows.windowless_python(str(tmp_path / "other")) == str(tmp_path / "other")


def test_windows_install_dry_run_changes_nothing_and_real_install_registers_then_starts(monkeypatch):
    calls = []
    monkeypatch.setattr(windows_tasks, "_IS_WINDOWS", True)
    monkeypatch.setattr(windows_tasks, "install_task", lambda *a, **k: calls.append(("install", a, k)))
    monkeypatch.setattr(windows_tasks, "start_task", lambda *a, **k: calls.append(("start", a)))
    manager = windows.WindowsTaskService()
    out = manager.install(ServiceSpec(python="C:\\py\\python.exe"), dry_run=True)
    assert calls == [] and any("PowerShell" in line for line in out)
    manager.install(ServiceSpec(python="C:\\py\\python.exe"))
    assert [c[0] for c in calls] == ["install", "start"]
    assert calls[0][2]["schedule_type"] == "ONLOGON" and calls[0][2]["run_level"] == "Limited"


def test_windows_status_maps_task_info(monkeypatch):
    monkeypatch.setattr(windows_tasks, "_IS_WINDOWS", True)
    monkeypatch.setattr(windows_tasks, "task_info", lambda name: {"state": "Running", "last_result": 0})
    st = windows.WindowsTaskService().status()
    assert st.installed and st.running
    monkeypatch.setattr(windows_tasks, "task_info", lambda name: None)
    assert not windows.WindowsTaskService().status().installed


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real Windows Task Scheduler")
def test_real_task_scheduler_round_trip():
    name = f"\\Hydra\\Test-{os.getpid()}"
    windows_tasks.install_task(
        name, f"{sys.executable} -c pass", schedule_type="ONLOGON", run_level="Limited", hidden=True, restart_count=3
    )
    try:
        info = windows_tasks.task_info(name)
        assert info is not None and info["state"] in {"Ready", "Running", "Disabled"}
    finally:
        windows_tasks.remove_task(name)
    assert windows_tasks.task_info(name) is None


# ------------------------------------------------------------------------------ systemd --user


def test_unit_text_quotes_paths_with_spaces_and_special_characters():
    unit = systemd_user.render_unit(ServiceSpec(python="/opt/my py/bin/python", data_dir="/data/100%/x"), "/data/100%/x")
    assert 'ExecStart="/opt/my py/bin/python" -m hydra_lite --service --data-dir /data/100%%/x' in unit
    assert "WorkingDirectory=/data/100%%/x" in unit
    for line in ("Restart=on-failure", "KillMode=control-group", "WantedBy=default.target", "StartLimitIntervalSec=0"):
        assert line in unit
    assert unit.index("StartLimitIntervalSec") < unit.index("[Service]")  # belongs to [Unit]


@pytest.fixture()
def fake_systemd(tmp_path, monkeypatch):
    """A `systemctl`/`loginctl` on PATH that records every call and answers is-active/is-enabled from files."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    state = tmp_path / "state"
    state.mkdir()
    (state / "active").write_text("inactive")
    (state / "enabled").write_text("disabled")
    script = f"""#!/bin/sh
echo "$0 $@" >> {log}
case "$*" in
  *is-active*) cat {state}/active; exit 0;;
  *is-enabled*) cat {state}/enabled; exit 0;;
  *"enable --now"*) echo active > {state}/active; echo enabled > {state}/enabled;;
  *"disable --now"*) echo inactive > {state}/active; echo disabled > {state}/enabled;;
  *" start "*|*" restart "*) echo active > {state}/active;;
  *" stop "*) echo inactive > {state}/active;;
esac
exit 0
"""
    for tool in ("systemctl", "loginctl"):
        p = bin_dir / tool
        p.write_text(script)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "hcfg"))
    return log


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shim")
def test_systemd_install_status_restart_and_remove(fake_systemd, capsys):
    assert main(["lite", "service", "install", "--python", "/usr/bin/python3"]) == 0
    unit = systemd_user.unit_path()
    assert unit.exists() and "/usr/bin/python3" in unit.read_text()
    calls = fake_systemd.read_text()
    assert "--user daemon-reload" in calls and "--user enable --now hydra.service" in calls
    assert main(["lite", "service", "status", "-o", "json"]) == 0
    assert '"running": true' in capsys.readouterr().out
    # installing again over a running unit is idempotent and restarts it onto the new command
    assert main(["lite", "service", "install", "--python", "/usr/bin/python3", "--port", "9001"]) == 0
    assert "--port 9001" in unit.read_text() and "restart hydra.service" in fake_systemd.read_text()
    assert main(["lite", "service", "stop"]) == 0
    assert main(["lite", "service", "status"]) == 1  # installed but not running
    assert main(["lite", "service", "remove"]) == 0
    assert not unit.exists() and main(["lite", "service", "status"]) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell shim")
def test_systemd_dry_run_and_no_start_and_linger(fake_systemd, capsys):
    assert main(["lite", "service", "install", "--dry-run", "--python", "/usr/bin/python3"]) == 0
    out = capsys.readouterr().out
    assert "ExecStart=/usr/bin/python3" in out and "dry run" in out
    assert not systemd_user.unit_path().exists() and not fake_systemd.exists()
    assert main(["lite", "service", "install", "--no-start", "--enable-linger", "--python", "/usr/bin/python3"]) == 0
    calls = fake_systemd.read_text()
    assert "enable hydra.service" in calls and "--now" not in calls and "enable-linger" in calls


def test_missing_systemd_is_explained(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert main(["lite", "service", "install", "--python", "/usr/bin/python3"]) == 1
    assert "systemctl was not found" in capsys.readouterr().err
