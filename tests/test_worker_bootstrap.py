"""Unit tests for worker.bootstrap and worker.windows_tasks.

These tests run on all platforms (Linux/macOS/Windows) and use mocking so
that no real Task Scheduler or process management is exercised.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IS_WINDOWS = platform.system().lower().startswith("win")


# ---------------------------------------------------------------------------
# windows_tasks — command building (no OS restriction)
# ---------------------------------------------------------------------------

from worker.windows_tasks import (
    _quote_arg,
    _require_windows,
    build_schtasks_create_command,
    build_schtasks_delete_command,
    build_schtasks_query_command,
)


class TestQuoteArg:
    def test_passthrough_clean_string(self):
        assert _quote_arg("hello") == "hello"

    def test_escapes_double_quotes(self):
        assert _quote_arg('say "hi"') == 'say ""hi""'

    def test_multiple_quotes(self):
        assert _quote_arg('"a" "b"') == '""a"" ""b""'


class TestBuildSchtasksCreateCommand:
    def test_basic_onstart(self):
        args = build_schtasks_create_command(
            task_name="\\Hydra\\Worker",
            command="python -m worker",
            working_dir=None,
            schedule_type="ONSTART",
            interval_minutes=5,
            run_as_system=False,
            description="test",
        )
        assert "schtasks" in args
        assert "/Create" in args
        assert "/F" in args
        assert "/TN" in args
        assert "\\Hydra\\Worker" in args
        assert "/SC" in args
        assert "ONSTART" in args
        # interval flag should NOT be present for ONSTART
        assert "/MO" not in args

    def test_minute_schedule_includes_interval(self):
        args = build_schtasks_create_command(
            task_name="\\Hydra\\Worker",
            command="python -m worker",
            working_dir=None,
            schedule_type="MINUTE",
            interval_minutes=10,
            run_as_system=False,
            description="test",
        )
        assert "/MO" in args
        idx = args.index("/MO")
        assert args[idx + 1] == "10"

    def test_run_as_system(self):
        args = build_schtasks_create_command(
            task_name="\\Hydra\\Worker",
            command="python -m worker",
            working_dir=None,
            schedule_type="ONSTART",
            interval_minutes=5,
            run_as_system=True,
            description="test",
        )
        assert "/RU" in args
        idx = args.index("/RU")
        assert args[idx + 1] == "SYSTEM"

    def test_highest_rl_always_present(self):
        args = build_schtasks_create_command(
            task_name="\\Hydra\\Worker",
            command="cmd",
            working_dir=None,
            schedule_type="ONSTART",
            interval_minutes=5,
            run_as_system=False,
            description="test",
        )
        assert "/RL" in args
        assert "HIGHEST" in args

    def test_command_is_double_quoted_in_tr(self):
        args = build_schtasks_create_command(
            task_name="\\Hydra\\Worker",
            command="C:\\Python311\\python.exe -m worker",
            working_dir=None,
            schedule_type="ONSTART",
            interval_minutes=5,
            run_as_system=False,
            description="test",
        )
        tr_idx = args.index("/TR")
        tr_value = args[tr_idx + 1]
        assert tr_value.startswith('"') and tr_value.endswith('"')


class TestBuildSchtasksDeleteCommand:
    def test_contains_delete_and_task_name(self):
        args = build_schtasks_delete_command("\\Hydra\\Worker")
        assert "schtasks" in args
        assert "/Delete" in args
        assert "/F" in args
        assert "\\Hydra\\Worker" in args


class TestBuildSchtasksQueryCommand:
    def test_contains_query_and_task_name(self):
        args = build_schtasks_query_command("\\Hydra\\Worker")
        assert "schtasks" in args
        assert "/Query" in args
        assert "\\Hydra\\Worker" in args
        assert "/FO" in args
        assert "LIST" in args


# ---------------------------------------------------------------------------
# windows_tasks — OS guard
# ---------------------------------------------------------------------------

class TestRequireWindows:
    @pytest.mark.skipif(IS_WINDOWS, reason="Only meaningful on non-Windows")
    def test_raises_on_non_windows(self):
        with pytest.raises(RuntimeError, match="only supported on Windows"):
            _require_windows()

    @pytest.mark.skipif(not IS_WINDOWS, reason="Only meaningful on Windows")
    def test_does_not_raise_on_windows(self):
        _require_windows()  # should not raise


class TestRunSchtasksOsGuard:
    @pytest.mark.skipif(IS_WINDOWS, reason="Non-Windows only")
    def test_run_schtasks_raises_on_non_windows(self):
        from worker.windows_tasks import run_schtasks
        with pytest.raises(RuntimeError, match="only supported on Windows"):
            run_schtasks(["schtasks", "/Query"])


# ---------------------------------------------------------------------------
# windows_tasks — install / remove / exists (mocked on all platforms)
# ---------------------------------------------------------------------------

class TestInstallTask:
    def test_install_calls_powershell_with_register_scheduled_task(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="Task registered successfully.", stderr="")
            from worker.windows_tasks import install_task
            install_task(
                task_name="\\Hydra\\Worker",
                command="python -m worker bootstrap run",
                schedule_type="ONSTART",
                interval_minutes=5,
            )
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "powershell"
            # The PowerShell script should register the task
            ps_script = call_args[-1]
            assert "Register-ScheduledTask" in ps_script

    def test_install_embeds_working_dir_in_ps_script(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            from worker.windows_tasks import install_task
            install_task(
                task_name="\\Hydra\\Worker",
                command="python -m worker bootstrap run",
                working_dir="C:\\hydra",
                schedule_type="ONSTART",
                interval_minutes=5,
            )
            call_args = mock_run.call_args[0][0]
            ps_script = call_args[-1]
            # The working dir should be passed via -WorkingDirectory in the PS script
            assert "WorkingDirectory" in ps_script
            assert "C:\\hydra" in ps_script

    def test_install_is_idempotent_with_force_flag(self):
        """Calling install twice should pass -Force each time — no error."""
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            from worker.windows_tasks import install_task
            for _ in range(2):
                install_task(
                    task_name="\\Hydra\\Worker",
                    command="python -m worker bootstrap run",
                    schedule_type="ONSTART",
                    interval_minutes=5,
                )
            assert mock_run.call_count == 2
            for call in mock_run.call_args_list:
                ps_script = call[0][0][-1]
                assert "-Force" in ps_script


class TestRemoveTask:
    def test_remove_calls_schtasks_delete(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="")
            from worker.windows_tasks import remove_task
            remove_task("\\Hydra\\Worker")
            call_args = mock_run.call_args[0][0]
            assert "/Delete" in call_args

    def test_remove_tolerates_task_not_found(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["schtasks"], output="", stderr="ERROR: The system cannot find the file specified."
            )
            from worker.windows_tasks import remove_task
            # Should not raise
            remove_task("\\Hydra\\Worker")

    def test_remove_raises_on_other_errors(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                5, ["schtasks"], output="", stderr="ERROR: Access is denied."
            )
            from worker.windows_tasks import remove_task
            with pytest.raises(subprocess.CalledProcessError):
                remove_task("\\Hydra\\Worker")


class TestTaskExists:
    def test_returns_true_when_query_succeeds(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="TaskName: \\Hydra\\Worker")
            from worker.windows_tasks import task_exists
            assert task_exists("\\Hydra\\Worker") is True

    def test_returns_false_when_query_fails(self):
        with mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, ["schtasks"])
            from worker.windows_tasks import task_exists
            assert task_exists("\\Hydra\\Worker") is False


# ---------------------------------------------------------------------------
# bootstrap — BootstrapConfig
# ---------------------------------------------------------------------------

from worker.bootstrap import BootstrapConfig


class TestBootstrapConfig:
    def test_defaults_from_env(self):
        env = {
            "API_TOKEN": "test-token",
            "REDIS_URL": "redis://localhost:6379/0",
            "HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL": "30",
            "HYDRA_BOOTSTRAP_INTERVAL_MINUTES": "5",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        assert cfg.api_token == "test-token"
        assert cfg.redis_url == "redis://localhost:6379/0"
        assert cfg.watchdog_interval_seconds == 30
        assert cfg.interval_minutes == 5

    def test_custom_task_name_from_env(self):
        env = {
            "API_TOKEN": "tok",
            "REDIS_URL": "redis://localhost:6379",
            "HYDRA_BOOTSTRAP_TASK_NAME": "\\Custom\\Task",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        assert cfg.task_name == "\\Custom\\Task"

    def test_validate_passes_with_required_env(self):
        env = {
            "API_TOKEN": "tok",
            "REDIS_URL": "redis://localhost:6379",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        errors = cfg.validate()
        assert errors == []

    def test_validate_fails_without_api_token(self):
        env = {
            "REDIS_URL": "redis://localhost:6379",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        errors = cfg.validate()
        assert any("API_TOKEN" in e for e in errors)

    def test_validate_fails_without_redis_url(self):
        env = {
            "API_TOKEN": "token",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        errors = cfg.validate()
        assert any("REDIS_URL" in e for e in errors)

    def test_validate_fails_with_tiny_watchdog_interval(self):
        env = {
            "API_TOKEN": "token",
            "REDIS_URL": "redis://localhost:6379",
            "HYDRA_BOOTSTRAP_WATCHDOG_INTERVAL": "2",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BootstrapConfig.from_env()
        errors = cfg.validate()
        assert any("WATCHDOG_INTERVAL" in e for e in errors)


# ---------------------------------------------------------------------------
# bootstrap — lock / PID helpers
# ---------------------------------------------------------------------------

from worker.bootstrap import (
    _is_pid_alive,
    _read_lock_pid,
    _remove_lock,
    _write_lock,
    acquire_bootstrap_lock,
)


class TestLockHelpers:
    def test_write_and_read_lock(self, tmp_path):
        lock_file = str(tmp_path / "test.lock")
        _write_lock(lock_file, 12345)
        assert _read_lock_pid(lock_file) == 12345

    def test_read_lock_returns_none_for_missing_file(self, tmp_path):
        lock_file = str(tmp_path / "missing.lock")
        assert _read_lock_pid(lock_file) is None

    def test_remove_lock_deletes_file(self, tmp_path):
        lock_file = str(tmp_path / "test.lock")
        _write_lock(lock_file, 1)
        _remove_lock(lock_file)
        assert not os.path.exists(lock_file)

    def test_remove_lock_is_idempotent(self, tmp_path):
        lock_file = str(tmp_path / "missing.lock")
        # Should not raise
        _remove_lock(lock_file)
        _remove_lock(lock_file)

    def test_acquire_lock_succeeds_when_no_existing_lock(self, tmp_path):
        lock_file = str(tmp_path / "test.lock")
        with mock.patch("worker.bootstrap.os.getpid", return_value=9999):
            acquired = acquire_bootstrap_lock(lock_file)
        assert acquired is True
        assert _read_lock_pid(lock_file) == 9999

    def test_acquire_lock_fails_when_alive_pid_holds_lock(self, tmp_path):
        lock_file = str(tmp_path / "test.lock")
        # Write a "foreign" PID to the lock file
        _write_lock(lock_file, 88888)
        with mock.patch("worker.bootstrap._is_pid_alive", return_value=True), \
             mock.patch("worker.bootstrap.os.getpid", return_value=99999):
            acquired = acquire_bootstrap_lock(lock_file)
        assert acquired is False

    def test_acquire_lock_succeeds_when_stale_pid_in_lock(self, tmp_path):
        lock_file = str(tmp_path / "test.lock")
        _write_lock(lock_file, 88888)
        with mock.patch("worker.bootstrap._is_pid_alive", return_value=False), \
             mock.patch("worker.bootstrap.os.getpid", return_value=99999):
            acquired = acquire_bootstrap_lock(lock_file)
        assert acquired is True


# ---------------------------------------------------------------------------
# bootstrap — is_pid_alive (cross-platform)
# ---------------------------------------------------------------------------

class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_not_alive(self):
        # PID 0 is typically not killable; use a known-dead PID
        assert _is_pid_alive(999999999) is False


# ---------------------------------------------------------------------------
# bootstrap — action_validate
# ---------------------------------------------------------------------------

from worker.bootstrap import action_validate


class TestActionValidate:
    def test_returns_0_with_valid_config(self, capsys):
        cfg = BootstrapConfig(
            api_token="token",
            redis_url="redis://localhost:6379",
            worker_command=f"{sys.executable} -m worker",
        )
        result = action_validate(cfg)
        assert result == 0
        captured = capsys.readouterr()
        assert "valid" in captured.out.lower()

    def test_returns_1_with_invalid_config(self, capsys):
        cfg = BootstrapConfig(
            api_token="",  # Missing token
            redis_url="redis://localhost:6379",
        )
        result = action_validate(cfg)
        assert result == 1
        captured = capsys.readouterr()
        assert "API_TOKEN" in captured.err


# ---------------------------------------------------------------------------
# bootstrap — action_install (mocked, non-Windows guard)
# ---------------------------------------------------------------------------

from worker.bootstrap import action_install, action_remove


class TestActionInstall:
    @pytest.mark.skipif(IS_WINDOWS, reason="Non-Windows only")
    def test_raises_on_non_windows(self):
        cfg = BootstrapConfig(api_token="tok", redis_url="redis://localhost:6379")
        with pytest.raises(RuntimeError, match="only supported on Windows"):
            action_install(cfg)

    def test_returns_1_on_invalid_config(self, capsys):
        with mock.patch("worker.bootstrap._IS_WINDOWS", True):
            cfg = BootstrapConfig(api_token="", redis_url="")
            result = action_install(cfg)
        assert result == 1

    def test_calls_install_task_on_windows(self, capsys):
        with mock.patch("worker.bootstrap._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            cfg = BootstrapConfig(
                api_token="tok",
                redis_url="redis://localhost:6379",
                task_name="\\Hydra\\TestWorker",
            )
            result = action_install(cfg)
        assert result == 0
        mock_run.assert_called_once()

    def test_install_is_idempotent(self, capsys):
        """Calling install twice should succeed without errors."""
        with mock.patch("worker.bootstrap._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            cfg = BootstrapConfig(
                api_token="tok",
                redis_url="redis://localhost:6379",
                task_name="\\Hydra\\TestWorker",
            )
            r1 = action_install(cfg)
            r2 = action_install(cfg)
        assert r1 == 0
        assert r2 == 0
        assert mock_run.call_count == 2


class TestActionRemove:
    @pytest.mark.skipif(IS_WINDOWS, reason="Non-Windows only")
    def test_raises_on_non_windows(self):
        cfg = BootstrapConfig(api_token="tok", redis_url="redis://localhost:6379")
        with pytest.raises(RuntimeError, match="only supported on Windows"):
            action_remove(cfg)

    def test_calls_remove_task_on_windows(self, capsys):
        with mock.patch("worker.bootstrap._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.return_value = mock.MagicMock(stdout="")
            cfg = BootstrapConfig(
                api_token="tok",
                redis_url="redis://localhost:6379",
                task_name="\\Hydra\\TestWorker",
            )
            result = action_remove(cfg)
        assert result == 0

    def test_remove_is_idempotent_when_task_not_found(self, capsys):
        with mock.patch("worker.bootstrap._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks._IS_WINDOWS", True), \
             mock.patch("worker.windows_tasks.run_schtasks") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["schtasks"], output="", stderr="ERROR: The system cannot find the file specified."
            )
            cfg = BootstrapConfig(
                api_token="tok",
                redis_url="redis://localhost:6379",
                task_name="\\Hydra\\TestWorker",
            )
            # Should not raise
            result = action_remove(cfg)
        assert result == 0


# ---------------------------------------------------------------------------
# bootstrap — watchdog duplicate-prevention
# ---------------------------------------------------------------------------

from worker.bootstrap import run_watchdog


class TestWatchdogDuplicatePrevention:
    def test_watchdog_exits_when_lock_not_acquired(self, tmp_path):
        lock_file = str(tmp_path / "watchdog.lock")
        cfg = BootstrapConfig(
            api_token="tok",
            redis_url="redis://localhost:6379",
            lock_file=lock_file,
        )
        with mock.patch("worker.bootstrap.acquire_bootstrap_lock", return_value=False):
            rc = run_watchdog(cfg)
        assert rc == 1

    def test_watchdog_starts_worker_when_not_alive(self, tmp_path):
        lock_file = str(tmp_path / "watchdog.lock")
        cfg = BootstrapConfig(
            api_token="tok",
            redis_url="redis://localhost:6379",
            lock_file=lock_file,
            watchdog_interval_seconds=5,
        )

        mock_proc = mock.MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # alive
        mock_proc.returncode = 0

        start_calls = []

        def fake_start(c):
            start_calls.append(c)
            return mock_proc

        import worker.bootstrap as bootstrap_mod

        # Run one iteration then stop
        iteration_count = [0]

        def fake_sleep(seconds):
            iteration_count[0] += 1
            if iteration_count[0] >= 1:
                bootstrap_mod._shutdown_requested = True

        with mock.patch.object(bootstrap_mod, "_start_worker", side_effect=fake_start), \
             mock.patch.object(bootstrap_mod.time, "sleep", side_effect=fake_sleep), \
             mock.patch.object(bootstrap_mod, "_is_worker_alive", return_value=False):
            bootstrap_mod._shutdown_requested = False
            rc = run_watchdog(cfg)

        assert len(start_calls) >= 1
        assert rc == 0

        # Clean up module-level flag
        bootstrap_mod._shutdown_requested = False
