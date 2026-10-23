"""Single-instance lock, rotating logs, and the real daemon process started the way a service manager does."""

import logging
import os
import signal
import socket
import subprocess
import sys
import time

import pytest

from cli._client import APIError, HydraClient
from hydra_lite import logging_setup
from hydra_lite.pidlock import AlreadyRunning, DaemonLock


def test_lock_is_exclusive_and_reusable(tmp_path):
    path = tmp_path / "daemon.lock"
    first = DaemonLock(path).acquire()
    with pytest.raises(AlreadyRunning) as exc:
        DaemonLock(path).acquire()
    assert exc.value.pid == os.getpid() and "already running" in str(exc.value)
    first.release()
    DaemonLock(path).acquire().release()


@pytest.mark.skipif(sys.platform == "win32", reason="uses SIGKILL")
def test_lock_dies_with_its_process_so_there_are_no_stale_locks(tmp_path):
    path = tmp_path / "daemon.lock"
    code = (
        "from hydra_lite.pidlock import DaemonLock; import time; "
        f"DaemonLock({str(path)!r}).acquire(); print('held', flush=True); time.sleep(60)"
    )
    holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(AlreadyRunning) as exc:
            DaemonLock(path).acquire()
        assert exc.value.pid == holder.pid
        holder.kill()
        holder.wait()
        DaemonLock(path).acquire().release()  # crash left no stale lock behind
    finally:
        holder.kill()


def test_rotating_file_logging_and_no_console_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "MAX_BYTES", 2000)
    log_file = tmp_path / "logs" / "daemon.log"
    logging_setup.configure_logging(log_file)
    logger = logging.getLogger("hydra_lite.test")
    for i in range(200):
        logger.info("line %s %s", i, "x" * 40)
    for h in logging.getLogger().handlers:
        h.flush()
    assert log_file.exists() and log_file.with_name("daemon.log.1").exists()
    assert log_file.stat().st_size <= 2000 + 200
    monkeypatch.setattr(sys, "stderr", None)  # pythonw.exe has no stderr
    logging_setup.configure_logging(None)
    logger.info("must not raise")
    logging_setup.configure_logging(None)  # restore a sane root for other tests


def test_rotate_if_large(tmp_path):
    f = tmp_path / "w.log"
    f.write_bytes(b"x" * 50)
    logging_setup.rotate_if_large(f, limit=10)
    assert not f.exists() and (tmp_path / "w.log.1").read_bytes() == b"x" * 50
    logging_setup.rotate_if_large(f, limit=10)  # missing file is fine


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _daemon(tmp_path, port, extra_env=None):
    env = {
        **os.environ,
        "HYDRA_DATA_DIR": str(tmp_path / "data"),
        "HYDRA_CONFIG_DIR": str(tmp_path / "cfg"),
        "HYDRA_WORKER_MODE": "inproc",
        **(extra_env or {}),
    }
    return subprocess.Popen(
        [sys.executable, "-m", "hydra_lite", "--service", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_health(port, proc, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"daemon exited early: {proc.stderr.read()}")
        try:
            return HydraClient(f"http://127.0.0.1:{port}", timeout=2).health()
        except APIError:
            time.sleep(0.2)
    raise AssertionError("daemon did not come up")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_second_daemon_on_the_same_data_dir_refuses_and_logs_go_to_a_rotating_file(tmp_path):
    port = _free_port()
    first = _daemon(tmp_path, port)
    try:
        assert _wait_health(port, first)["edition"] == "lite"
        second = _daemon(tmp_path, _free_port())
        _, err = second.communicate(timeout=30)
        assert second.returncode == 3 and "already running" in err
        log = (tmp_path / "data" / "daemon.log").read_text()
        assert "Uvicorn running" in log or "Application startup complete" in log  # service mode logs to the file
        first.send_signal(signal.SIGTERM)
        # uvicorn finishes its graceful shutdown and then re-raises SIGTERM; systemd treats that as a clean stop
        assert first.wait(timeout=40) in (0, -signal.SIGTERM)
        assert "Finished server process" in (tmp_path / "data" / "daemon.log").read_text()
        # after a clean exit the lock is free again
        DaemonLock(tmp_path / "data" / "daemon.lock").acquire().release()
    finally:
        if first.poll() is None:
            first.kill()


def test_port_in_use_fails_loudly(tmp_path):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        proc = _daemon(tmp_path, busy.getsockname()[1])
        _, err = proc.communicate(timeout=40)
    assert proc.returncode != 0
    assert (
        "address already in use" in (tmp_path / "data" / "daemon.log").read_text().lower()
        or "address already in use" in err.lower()
    )
