import io
import json
import urllib.error
from pathlib import Path

import pytest

from cli.__main__ import main
from cli._client import APIError, HydraClient


class FakeClient:
    def __init__(self, responses=None, events=None):
        self.responses = responses or {}
        self.events = events or []
        self.calls = []

    def request(self, method, path, *, body=None, query=None):
        self.calls.append((method, path, body, query))
        response = self.responses.get((method, path))
        if isinstance(response, Exception):
            raise response
        if response is None and (method, path) not in self.responses:
            raise AssertionError(f"unexpected request: {method} {path}")
        return response

    def stream_sse(self, path):
        self.calls.append(("STREAM", path, None, None))
        yield from self.events


def invoke(client, *args):
    return main(list(args), client_factory=lambda *unused, **also_unused: client)


def test_get_jobs_renders_a_table(capsys):
    client = FakeClient({("GET", "/jobs/"): [{"_id": "job-1", "name": "nightly", "enabled": True, "domain": "prod"}]})

    assert invoke(client, "get", "jobs") == 0

    output = capsys.readouterr().out
    assert "NAME" in output
    assert "nightly" in output
    assert "job-1" in output
    assert client.calls == [("GET", "/jobs/", None, {"limit": 100, "search": None})]


def test_get_resources_can_emit_json(capsys):
    workers = [{"worker_id": "worker-1", "domain": "prod"}]
    client = FakeClient({("GET", "/workers/"): workers})

    assert invoke(client, "get", "workers", "-o", "json") == 0

    assert json.loads(capsys.readouterr().out) == workers


def test_run_resolves_exact_job_name_and_parses_params(capsys):
    client = FakeClient(
        {
            ("GET", "/jobs/nightly"): APIError("not found", 404),
            ("GET", "/jobs/"): [{"_id": "job-1", "name": "nightly"}],
            ("POST", "/jobs/job-1/run"): {"job_id": "job-1", "queued": True},
        }
    )

    assert invoke(client, "run", "nightly", "--param", "date=2026-07-22", "--param", "retries=2", "-o", "json") == 0

    assert client.calls[-1] == (
        "POST",
        "/jobs/job-1/run",
        {"params": {"date": "2026-07-22", "retries": 2}},
        None,
    )
    assert json.loads(capsys.readouterr().out)["queued"] is True


def test_apply_reads_yaml(capsys):
    definition = Path(__file__).parent / "fixtures" / "cli_job.yaml"
    client = FakeClient({("POST", "/jobs/"): {"_id": "job-2", "name": "report"}})

    assert invoke(client, "apply", "-f", str(definition), "-o", "json") == 0

    assert client.calls[0][2]["executor"]["script"] == "echo ok"
    assert json.loads(capsys.readouterr().out)["_id"] == "job-2"


def test_logs_prints_stdout_and_stderr(capsys):
    client = FakeClient({("GET", "/runs/run-1"): {"stdout": "done\n", "stderr": "warning\n"}})

    assert invoke(client, "logs", "run-1") == 0

    captured = capsys.readouterr()
    assert captured.out == "done\n"
    assert captured.err == "warning\n"


def test_follow_logs_prints_stream_chunks(capsys):
    events = [("log_chunk", {"stream": "stdout", "text": "one\n"}), ("log_chunk", {"stream": "stderr", "text": "two\n"})]
    client = FakeClient(events=events)

    assert invoke(client, "logs", "run-1", "--follow") == 0

    assert capsys.readouterr().out == "one\ntwo\n"
    assert client.calls == [("STREAM", "/runs/run-1/stream", None, None)]


def test_backfill_uses_api_date_field_names(capsys):
    client = FakeClient(
        {
            ("GET", "/jobs/job-1"): {"_id": "job-1"},
            ("POST", "/jobs/job-1/backfill"): {"queued_count": 2},
        }
    )

    assert invoke(client, "backfill", "job-1", "--from", "2026-07-20", "--to", "2026-07-21") == 0

    assert client.calls[-1][2] == {"start_date": "2026-07-20", "end_date": "2026-07-21"}
    assert "queued_count: 2" in capsys.readouterr().out


def test_api_errors_have_a_nonzero_exit(capsys):
    client = FakeClient({("GET", "/history/"): APIError("API returned 503: unavailable", 503)})

    assert invoke(client, "get", "runs") == 1

    assert "503" in capsys.readouterr().err


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_http_client_sends_auth_headers_and_query(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return FakeResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = HydraClient("https://hydra.example/", token="secret", domain="billing", timeout=12)

    assert client.request("GET", "/jobs/", query={"search": "daily report"}) == {"ok": True}

    assert seen["request"].full_url == "https://hydra.example/jobs/?search=daily+report"
    assert seen["request"].get_header("X-api-key") == "secret"
    assert seen["request"].get_header("X-domain") == "billing"
    assert seen["timeout"] == 12


def test_http_client_decodes_api_error(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"detail":"wrong domain"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(APIError, match="wrong domain") as raised:
        HydraClient("https://hydra.example").request("GET", "/jobs/")

    assert raised.value.status == 403
