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
        overrides={"data_dir": tmp_path, "max_concurrency": 2, "worker_mode": "inproc", **overrides},
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


def start_live(daemon):
    """Serve ``daemon`` on a real loopback port (urllib clients and subprocess workers need a socket)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    daemon.config.port = port
    daemon.base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(create_app(daemon), host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    return f"http://127.0.0.1:{port}", server, thread


def stop_live(server, thread):
    server.should_exit = True
    thread.join(timeout=30)


@pytest.fixture()
def live_server(daemon):
    """A real uvicorn on a free loopback port (urllib-based hydra-ctl needs a socket)."""
    url, server, thread = start_live(daemon)
    yield url, daemon.token
    stop_live(server, thread)


@pytest.fixture()
def sub_daemon(tmp_path):
    """A daemon that supervises real worker processes (one permanent worker by default)."""
    return Daemon(make_config(tmp_path, worker_mode="subprocess", default_workers=1, max_workers=3, heartbeat_ttl=3.0))


@pytest.fixture()
def sub_live(sub_daemon):
    url, server, thread = start_live(sub_daemon)
    from cli._client import HydraClient

    api = HydraClient(url, token=sub_daemon.token, timeout=30)
    wait_for(lambda: any(w["connectivity_status"] == "online" for w in api.request("GET", "/workers/")), timeout=30)
    yield api, sub_daemon
    stop_live(server, thread)


@pytest.fixture()
def proto_client(tmp_path):
    """TestClient on a subprocess-mode daemon that never spawns workers: tests play the worker by hand."""
    d = Daemon(make_config(tmp_path, worker_mode="subprocess", default_workers=0, max_workers=0))
    with TestClient(create_app(d), headers={"x-api-key": d.token}) as c:
        yield c, d


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
