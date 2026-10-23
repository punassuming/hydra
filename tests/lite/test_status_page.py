"""The read-only status page: served without data, driven by the authenticated API, rendered by a real browser."""

import os
import re
import shutil
import subprocess
import sys

import pytest
from conftest import py_job, wait_for

from cli.__main__ import main


def test_page_is_public_but_contains_no_data_or_token(client, daemon):
    r = client.get("/", headers={"x-api-key": ""})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert daemon.token not in r.text and "Hydra" in r.text
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/jobs/", headers={"x-api-key": ""}).status_code == 401  # the data stays behind the token


def test_page_never_injects_markup_from_data():
    html = (
        open(
            os.path.join(os.path.dirname(__file__), "..", "..", "hydra_lite", "daemon", "static", "index.html"), encoding="utf-8"
        )
    ).read()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in html, f"{banned} would let a job name or log line inject script"
    assert "https://" not in html and "http://" not in re.sub(r"https?://www\.w3\.org", "", html)  # no CDN, works offline


def test_page_is_packaged():
    from importlib import resources

    assert resources.files("hydra_lite.daemon").joinpath("static/index.html").is_file()


def test_ui_command_prints_a_fragment_url_with_the_token(daemon, live_server, monkeypatch, capsys):
    url, token = live_server
    monkeypatch.setenv("HYDRA_DATA_DIR", str(daemon.config.data_dir))
    assert main(["--api-url", url, "lite", "ui", "--no-open"]) == 0
    assert capsys.readouterr().out.strip() == f"{url}/#token={token}"


def _chromium():
    candidates = [
        os.getenv("HYDRA_TEST_BROWSER"),
        os.path.join(os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"), "chromium"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
    ]
    return next((c for c in candidates if c and os.path.exists(c)), None)


@pytest.mark.skipif(
    _chromium() is None or not sys.platform.startswith("linux"), reason="needs a headless Chromium (set HYDRA_TEST_BROWSER)"
)
def test_headless_browser_renders_runs_jobs_workers_and_logs(daemon, live_server, tmp_path):
    from cli._client import HydraClient

    url, token = live_server
    api = HydraClient(url, token=token, timeout=30)
    job = api.request(
        "POST",
        "/jobs/",
        body={
            **py_job("render-me", "print('hello <b>bold</b> from the log')"),
            "schedule": {"mode": "cron", "cron": "0 0 1 1 *"},
        },
    )
    rid = api.request("POST", f"/jobs/{job['_id']}/run", body={})["run_id"]
    wait_for(lambda: api.request("GET", f"/runs/{rid}")["status"] == "success")

    def dump(fragment):
        out = subprocess.run(
            [
                _chromium(),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={tmp_path / 'profile'}",
                "--virtual-time-budget=6000",
                "--dump-dom",
                f"{url}/{fragment}",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return out.stdout

    dom = dump(f"#token={token}")
    assert "render-me" in dom and "✓ success" in dom and "lite edition" in dom
    assert token not in dom  # the fragment token is moved out of the page and never rendered
    assert "<b>bold</b>" not in dom or "&lt;b&gt;bold" in dom  # markup in data is text, not elements
    no_token = dump("")
    assert "Sign in" in no_token and "render-me" not in no_token
