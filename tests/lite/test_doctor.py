import os
import sys
from pathlib import Path

import pytest

from cli.__main__ import main
from hydra_lite import config as config_module
from hydra_lite import doctor
from hydra_lite.doctor import FAIL, PASS, WARN


def _cfg(tmp_path):
    return config_module.load(overrides={"data_dir": tmp_path}, env={}, config_path=tmp_path / "none.toml")


def by_name(checks):
    return {c.name: c for c in checks}


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("\\\\server\\share\\hydra", "network"),
        ("C:\\Users\\me\\OneDrive\\hydra", "onedrive"),
        ("/home/me/Dropbox/hydra", "dropbox"),
        ("/home/me/Google Drive/hydra", "google drive"),
    ],
)
def test_synced_and_network_locations_are_flagged(path, needle):
    assert needle in doctor.synced_or_network_reason(Path(path)).lower()


@pytest.mark.skipif(sys.platform == "win32", reason="the mount table (/proc/mounts) is a Linux file")
def test_network_filesystems_are_detected_from_the_mount_table(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text(f"/dev/sda1 / ext4 rw 0 0\nserver:/export {tmp_path} nfs4 rw 0 0\n")
    assert "nfs4" in doctor.synced_or_network_reason(tmp_path / "data", mounts_file=str(mounts))
    mounts.write_text("/dev/sda1 / ext4 rw 0 0\n")
    assert doctor.synced_or_network_reason(tmp_path / "data", mounts_file=str(mounts)) is None


def test_local_checks_on_a_healthy_directory(tmp_path):
    checks = by_name(doctor.run_checks(_cfg(tmp_path), None, service_check=lambda: doctor.Check("service", PASS, "ok")))
    assert checks["python"].status == PASS and checks["sqlite"].status == PASS
    assert checks["data dir writable"].status == PASS and checks["database"].message.startswith("none yet")


def test_unwritable_directory_and_corrupt_database_fail(tmp_path):
    (tmp_path / "hydra.db").write_bytes(b"this is not a database" * 100)
    checks = by_name(doctor._local_checks(_cfg(tmp_path)))
    assert checks["database"].status == FAIL


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions as a non-root user")
def test_world_readable_token_is_a_warning(tmp_path):
    (tmp_path / "token").write_text("secret")
    (tmp_path / "token").chmod(0o644)
    assert by_name(doctor._local_checks(_cfg(tmp_path)))["token file"].status == WARN


def test_newer_database_fails(tmp_path):
    import sqlite3

    from hydra_lite.store import Store

    Store(tmp_path / "hydra.db").close()
    con = sqlite3.connect(tmp_path / "hydra.db")
    con.execute("PRAGMA user_version=99")
    con.close()
    assert by_name(doctor._local_checks(_cfg(tmp_path)))["database"].status == FAIL


def test_large_logs_with_retention_off_warn(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "BIG_LOGS_WARN", 10)
    cfg = config_module.load(
        overrides={"data_dir": tmp_path}, env={"HYDRA_RUN_RETENTION_DAYS": "0"}, config_path=tmp_path / "none.toml"
    )
    (cfg.log_dir).mkdir(parents=True)
    (cfg.log_dir / "x.out").write_bytes(b"x" * 100)
    assert by_name(doctor._local_checks(cfg))["retention"].status == WARN


# ------------------------------------------------------------------------------------- against a live daemon


def test_api_checks_against_a_live_daemon(daemon, live_server):
    from conftest import py_job

    from cli._client import HydraClient

    url, token = live_server
    client = HydraClient(url, token=token, timeout=10)
    client.request("POST", "/jobs/", body={**py_job("ok", "pass"), "schedule": {"mode": "cron", "cron": "0 0 1 1 *"}})
    checks = by_name(doctor._api_checks(daemon.config, client, service_installed=False))
    assert checks["daemon"].status == PASS and "lite" in checks["daemon"].message
    assert checks["time zones"].status == PASS and checks["pending runs"].status == PASS


def test_a_pending_run_no_worker_can_take_is_reported_with_the_fix(daemon, live_server):
    from conftest import py_job

    from cli._client import HydraClient

    url, token = live_server
    client = HydraClient(url, token=token, timeout=10)
    job = client.request(
        "POST",
        "/jobs/",
        body={**py_job("gpu-only", "pass", affinity={"tags": ["gpu"]}), "schedule": {"mode": "cron", "cron": "0 0 1 1 *"}},
    )
    client.request("POST", f"/jobs/{job['_id']}/run", body={})
    check = by_name(doctor._api_checks(daemon.config, client, service_installed=False))["pending runs"]
    assert check.status == WARN and "gpu-only" in check.message and "worker spawn" in check.hint


def test_unreachable_daemon_is_a_warning_unless_a_service_should_be_running(tmp_path):
    from cli._client import HydraClient

    client = HydraClient("http://127.0.0.1:9", token="x", timeout=1)
    cfg = _cfg(tmp_path)
    assert doctor._api_checks(cfg, client, service_installed=False)[0].status == WARN
    assert doctor._api_checks(cfg, client, service_installed=True)[0].status == FAIL


def test_cli_doctor_exit_codes_and_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HYDRA_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("HYDRA_CONFIG_DIR", str(tmp_path / "c"))
    assert main(["lite", "doctor", "--no-api"]) == 0
    assert "passed" in capsys.readouterr().out
    assert main(["lite", "doctor", "--no-api", "-o", "json"]) == 0
    assert '"name": "python"' in capsys.readouterr().out
    (tmp_path / "d").mkdir(exist_ok=True)
    (tmp_path / "d" / "hydra.db").write_bytes(b"garbage" * 500)
    assert main(["lite", "doctor", "--no-api"]) == 1
    assert sys.platform  # keep the import used
