#!/usr/bin/env python3
"""Install Hydra into a fresh virtualenv WITHOUT extras and run a job through the lite edition.

Proves the lean dependency set is enough (and that Redis/MongoDB/AI SDKs are not dragged in):

    uv run python scripts/lite_install_smoke.py            # builds a temp venv with `uv`
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEAVY = ["redis", "pymongo", "openai", "google.genai", "cryptography", "sqlalchemy", "sse_starlette", "dotenv"]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv is required", file=sys.stderr)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="hydra-smoke-"))
    venv = tmp / "venv"
    run([uv, "venv", str(venv)])
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([uv, "pip", "install", "--python", str(py), str(ROOT)])
    present = json.loads(
        run(
            [
                str(py),
                "-c",
                f"import importlib.util as u, json; print(json.dumps([m for m in {HEAVY!r} if u.find_spec(m.split('.')[0])]))",
            ],
            cwd=tmp,
        ).stdout
    )
    if present:
        print(f"FAIL: lean install pulled in {present}", file=sys.stderr)
        return 1
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "HYDRA_DATA_DIR": str(tmp / "data"),
        "HYDRA_CONFIG_DIR": str(tmp / "cfg"),
        "HYDRA_PORT": str(port),
        "HYDRA_API_URL": f"http://127.0.0.1:{port}",
        "HYDRA_DEFAULT_WORKERS": "1",
    }
    ctl = [str(venv / ("Scripts/hydra-ctl.exe" if os.name == "nt" else "bin/hydra-ctl"))]
    daemon = subprocess.Popen(
        [str(py), "-m", "hydra_lite", "--service"], env=env, cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    try:
        for _ in range(100):
            if daemon.poll() is not None:
                print(f"FAIL: daemon exited: {daemon.stderr.read()}", file=sys.stderr)
                return 1
            if subprocess.run(ctl + ["lite", "daemon", "status"], env=env, capture_output=True).returncode == 0:
                break
            time.sleep(0.3)
        job = tmp / "job.yaml"
        job.write_text(
            "name: smoke\n"
            "executor: {type: python, code: \"print('lean install works')\"}\n"
            "schedule: {mode: cron, cron: '0 0 1 1 *'}\n"
        )
        run(ctl + ["apply", "-f", str(job)], env=env)
        out = run(ctl + ["run", "smoke", "--wait", "-o", "json"], env=env).stdout
        result = json.loads(out)["run"]
        if result["status"] != "success" or "lean install works" not in result["stdout"]:
            print(f"FAIL: unexpected run result: {result}", file=sys.stderr)
            return 1
        print("OK: lean install ran a job through the lite edition; no heavy packages installed")
        return 0
    finally:
        daemon.terminate()
        try:
            daemon.wait(30)
        except subprocess.TimeoutExpired:
            daemon.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
