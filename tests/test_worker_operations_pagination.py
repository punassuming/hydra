import json
import os

import pytest
from fastapi.testclient import TestClient

from scheduler.main import app

_TEST_ADMIN_TOKEN = "test-admin-token-worker-ops"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _auth_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}


class _FakeRedis:
    def __init__(self, worker_key: str, events: list[dict]):
        self._worker_key = worker_key
        self._list = [json.dumps(e) for e in events]

    def exists(self, key):
        return 1 if key == self._worker_key else 0

    def hgetall(self, key):
        return {}

    def lrange(self, key, start, end):
        if key != "worker_ops:prod:worker-1":
            return []
        # Mimic Redis's inclusive, possibly-negative-indexed LRANGE closely
        # enough for the (0, -1) "whole list" call this endpoint makes.
        if start == 0 and end == -1:
            return list(self._list)
        raise NotImplementedError("only the full-range call is exercised by this endpoint")


def _events(n):
    return [{"ts": float(i), "type": "dispatch", "message": f"event {i}", "details": {}} for i in range(n)]


def test_operations_returns_first_page_newest_first():
    redis = _FakeRedis("workers:prod:worker-1", _events(5))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        resp = client.get("/workers/worker-1/operations?domain=prod&limit=2", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert [e["ts"] for e in data["events"]] == [4.0, 3.0]
    assert data["has_more"] is True
    assert data["next_before_ts"] == 3.0


def test_operations_before_ts_cursor_advances_to_older_events():
    redis = _FakeRedis("workers:prod:worker-1", _events(5))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        first = client.get("/workers/worker-1/operations?domain=prod&limit=2", headers=_auth_headers()).json()
        second = client.get(
            f"/workers/worker-1/operations?domain=prod&limit=2&before_ts={first['next_before_ts']}", headers=_auth_headers()
        ).json()
    assert [e["ts"] for e in second["events"]] == [2.0, 1.0]
    assert second["has_more"] is True


def test_operations_last_page_has_no_next_cursor():
    redis = _FakeRedis("workers:prod:worker-1", _events(3))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        resp = client.get("/workers/worker-1/operations?domain=prod&limit=10", headers=_auth_headers())
    data = resp.json()
    assert len(data["events"]) == 3
    assert data["has_more"] is False
    assert data["next_before_ts"] is None


def test_operations_rejects_invalid_limit():
    redis = _FakeRedis("workers:prod:worker-1", _events(1))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        resp = client.get("/workers/worker-1/operations?domain=prod&limit=nope", headers=_auth_headers())
    assert resp.status_code == 400


def test_operations_rejects_invalid_before_ts():
    redis = _FakeRedis("workers:prod:worker-1", _events(1))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        resp = client.get("/workers/worker-1/operations?domain=prod&before_ts=nope", headers=_auth_headers())
    assert resp.status_code == 400


def test_operations_clamps_limit_to_200():
    redis = _FakeRedis("workers:prod:worker-1", _events(3))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scheduler.api.workers.get_redis", lambda: redis)
        resp = client.get("/workers/worker-1/operations?domain=prod&limit=10000", headers=_auth_headers())
    assert resp.status_code == 200
    assert len(resp.json()["events"]) == 3
