import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from hydra_lite import config as config_module
from hydra_lite.daemon.app import create_app
from hydra_lite.daemon.runtime import Daemon


def make_config(tmp_path, **overrides):
    return config_module.load(
        overrides={"data_dir": tmp_path, "max_concurrency": 2, **overrides},
        env={},
        config_path=tmp_path / "none.toml",
    )


@pytest.fixture()
def daemon(tmp_path):
    return Daemon(make_config(tmp_path))


@pytest.fixture()
def client(daemon):
    app = create_app(daemon)
    with TestClient(app, headers={"x-api-key": daemon.token}) as c:
        yield c


@pytest.fixture()
def live_server(daemon):
    """A real uvicorn on a free loopback port (urllib-based hydra-ctl needs a socket)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(daemon), host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}", daemon.token
    server.should_exit = True
    thread.join(timeout=10)


def wait_for(predicate, timeout=15.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


def py_job(name, code, **extra):
    return {"name": name, "executor": {"type": "python", "code": code}, **extra}
