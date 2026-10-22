"""hydra-ctl driven against a real lite daemon over HTTP."""

import json

import pytest
import yaml
from conftest import wait_for

from cli.__main__ import main

JOB = {
    "name": "ctl-job",
    "executor": {"type": "python", "code": "import os; print('P=' + os.environ.get('P', '-'))"},
    "schedule": {"mode": "cron", "cron": "0 0 1 1 *"},
}


@pytest.fixture()
def ctl(live_server, capsys, tmp_path):
    url, token = live_server

    def run(*argv, token_arg=True):
        base = ["--api-url", url] + (["--token", token] if token_arg else [])
        code = main([*base, *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def _apply(ctl, tmp_path, doc=JOB):
    path = tmp_path / "job.yaml"
    path.write_text(yaml.safe_dump(doc))
    code, out, _ = ctl("apply", "-f", str(path), "-o", "json")
    assert code == 0
    return json.loads(out)


def test_apply_get_describe_validate_delete(ctl, tmp_path):
    job = _apply(ctl, tmp_path)
    code, out, _ = ctl("get", "jobs", "-o", "json")
    assert code == 0 and [j["name"] for j in json.loads(out)] == ["ctl-job"]
    code, out, _ = ctl("get", "jobs")  # table rendering must not choke on lite rows
    assert code == 0 and "ctl-job" in out
    code, out, _ = ctl("describe", "job", "ctl-job", "-o", "json")  # resolves by name
    assert json.loads(out)["_id"] == job["_id"]
    path = tmp_path / "job.yaml"
    code, out, _ = ctl("validate", "-f", str(path), "-o", "json")
    assert json.loads(out)["valid"] is True
    assert ctl("delete", "job", "ctl-job", "-o", "json")[0] == 0
    code, _, err = ctl("describe", "job", "ctl-job")
    assert code == 4 and "was not found" in err  # EXIT_NOT_FOUND


def test_run_wait_logs_and_history(ctl, tmp_path, capsys):
    _apply(ctl, tmp_path)
    code, out, _ = ctl("run", "ctl-job", "--param", "P=42", "--wait", "-o", "json")
    assert code == 0
    result = json.loads(out)
    assert result["queued"] is True and result["run"]["status"] == "success"
    run_id = result["run"]["_id"]
    code, out, _ = ctl("logs", run_id)
    assert code == 0 and "P=42" in out
    code, out, _ = ctl("get", "runs", "-o", "json")
    assert json.loads(out)[0]["_id"] == run_id
    code, out, _ = ctl("get", "runs")
    assert code == 0 and run_id[:8] in out or "success" in out
    code, out, _ = ctl("describe", "run", run_id, "-o", "json")
    assert json.loads(out)["returncode"] == 0
    # retry re-queues the job that produced the run
    assert ctl("retry", run_id, "-o", "json")[0] == 0


def test_logs_follow_uses_sse(ctl, tmp_path):
    _apply(ctl, tmp_path)
    _, out, _ = ctl("run", "ctl-job", "--wait", "-o", "json")
    run_id = json.loads(out)["run"]["_id"]
    code, out, _ = ctl("logs", run_id, "--follow")
    assert code == 0 and "P=-" in out


def test_kill_wait(ctl, tmp_path):
    doc = {**JOB, "name": "sleepy", "executor": {"type": "python", "code": "import time; time.sleep(60)"}}
    _apply(ctl, tmp_path, doc)
    ctl("run", "sleepy", "-o", "json")
    job_id = json.loads(ctl("describe", "job", "sleepy", "-o", "json")[1])["_id"]
    run = wait_for(
        lambda: [r for r in json.loads(ctl("get", "runs", "-o", "json")[1]) if r["job_id"] == job_id and r["status"] == "running"]
    )
    code, out, _ = ctl("kill", run[0]["_id"], "--wait", "-o", "json")
    assert code == 0 and json.loads(out)["run"]["status"] == "failed"


def test_workers_and_doctor(ctl):
    code, out, _ = ctl("get", "workers", "-o", "json")
    workers = json.loads(out)
    assert code == 0 and workers[0]["connectivity_status"] == "online"
    assert ctl("worker", "state", workers[0]["worker_id"], "online", "-o", "json")[0] == 0
    code, out, _ = ctl("doctor", "-o", "json")
    assert code == 0 and json.loads(out)["health"]["edition"] == "lite"
    for view in ("statistics", "queue", "pressure"):
        assert ctl("overview", view, "-o", "json")[0] == 0


def test_unsupported_commands_explain_themselves(ctl, tmp_path):
    code, _, err = ctl("token", "rotate")
    assert code == 1 and "not supported by this Hydra edition" in err
    _apply(ctl, tmp_path)
    code, _, err = ctl("backfill", "ctl-job", "--from", "2026-01-01", "--to", "2026-01-02")
    assert code == 1 and "not supported" in err


def test_exit_codes_are_stable(ctl, tmp_path, live_server):
    doc = {**JOB, "name": "boom", "executor": {"type": "python", "code": "raise SystemExit(7)"}}
    _apply(ctl, tmp_path, doc)
    assert ctl("run", "boom", "--wait", "-o", "json")[0] == 5  # EXIT_RUN_FAILED
    assert ctl("describe", "run", "nope")[0] == 4  # EXIT_NOT_FOUND
    assert main(["--api-url", "http://127.0.0.1:9", "--timeout", "1", "--token", "x", "get", "jobs"]) == 3  # EXIT_UNREACHABLE


def test_wrong_token_is_rejected(live_server, capsys):
    url, _ = live_server
    assert main(["--api-url", url, "--token", "nope", "get", "jobs"]) == 1
    assert "invalid or missing API token" in capsys.readouterr().err


def test_token_file_fallback_for_loopback(live_server, daemon, monkeypatch, capsys):
    url, _ = live_server
    monkeypatch.setenv("HYDRA_DATA_DIR", str(daemon.config.data_dir))
    monkeypatch.delenv("HYDRA_TOKEN", raising=False)
    assert main(["--api-url", url, "get", "jobs", "-o", "json"]) == 0
    capsys.readouterr()


def test_lite_daemon_status_and_config(live_server, daemon, monkeypatch, capsys):
    url, token = live_server
    monkeypatch.setenv("HYDRA_DATA_DIR", str(daemon.config.data_dir))
    assert main(["--api-url", url, "lite", "daemon", "status", "-o", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["edition"] == "lite"
    assert main(["lite", "config", "path"]) == 0
    assert str(daemon.config.data_dir) in capsys.readouterr().out
    assert main(["--api-url", "http://127.0.0.1:9", "--timeout", "1", "lite", "daemon", "status"]) == 3


def test_lite_daemon_stop_endpoint_needs_runner(live_server, capsys):
    url, token = live_server
    # the fixture's server was not started via hydra's runner, so shutdown reports why
    assert main(["--api-url", url, "--token", token, "lite", "daemon", "stop"]) == 1
    assert "stop it from its supervisor" in capsys.readouterr().err
