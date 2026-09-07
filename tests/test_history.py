import base64
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from scheduler.main import app

_TEST_ADMIN_TOKEN = "test-admin-token-history"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _set_admin_token():
    os.environ["ADMIN_TOKEN"] = _TEST_ADMIN_TOKEN
    yield
    os.environ.pop("ADMIN_TOKEN", None)


def _auth_headers():
    return {"x-api-key": _TEST_ADMIN_TOKEN}


def _matches(doc, query):
    for key, cond in query.items():
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
        elif key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
        elif isinstance(cond, dict):
            value = doc.get(key)
            if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                return False
        else:
            if doc.get(key) != cond:
                return False
    return True


class _FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key_or_list, direction=None):
        keys = [(key_or_list, direction)] if direction is not None else key_or_list
        for key, key_direction in reversed(keys):
            self.docs.sort(key=lambda d: d[key], reverse=key_direction < 0)
        return self

    def limit(self, n):
        return self.docs[:n]

    def __iter__(self):
        return iter(self.docs)


class _FakeJobRuns:
    def __init__(self, runs):
        self._runs = runs

    def find(self, query):
        return _FakeCursor([r for r in self._runs if _matches(r, query)])


class _FakeDB:
    def __init__(self, runs):
        self.job_runs = _FakeJobRuns(runs)


def _now():
    return datetime.now(timezone.utc)


def _run(run_id, domain, start_ts):
    return {"_id": run_id, "job_id": "job-1", "domain": domain, "status": "success", "start_ts": start_ts}


def test_unpaged_history_returns_a_plain_list_backward_compatible():
    runs = [_run("r1", "prod", _now())]
    with patch("scheduler.api.history.get_db", return_value=_FakeDB(runs)):
        resp = client.get("/history/", headers=_auth_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert resp.json()[0]["_id"] == "r1"


def test_paged_history_returns_items_next_cursor_has_more():
    base = _now()
    runs = [_run(f"r{i}", "prod", base - timedelta(minutes=i)) for i in range(5)]
    with patch("scheduler.api.history.get_db", return_value=_FakeDB(runs)):
        resp = client.get("/history/?paged=true&limit=2", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert [item["_id"] for item in data["items"]] == ["r0", "r1"]
    assert data["has_more"] is True
    assert data["next_cursor"]


def test_paged_history_cursor_advances_to_the_next_page():
    base = _now()
    runs = [_run(f"r{i}", "prod", base - timedelta(minutes=i)) for i in range(5)]
    with patch("scheduler.api.history.get_db", return_value=_FakeDB(runs)):
        first = client.get("/history/?paged=true&limit=2", headers=_auth_headers()).json()
        second = client.get(
            f"/history/?paged=true&limit=2&cursor={first['next_cursor']}", headers=_auth_headers()
        ).json()
    assert [item["_id"] for item in second["items"]] == ["r2", "r3"]
    assert second["has_more"] is True


def test_paged_history_last_page_has_no_next_cursor():
    base = _now()
    runs = [_run(f"r{i}", "prod", base - timedelta(minutes=i)) for i in range(3)]
    with patch("scheduler.api.history.get_db", return_value=_FakeDB(runs)):
        resp = client.get("/history/?paged=true&limit=10", headers=_auth_headers())
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["has_more"] is False
    assert data["next_cursor"] is None


def test_paged_history_rejects_invalid_cursor():
    with patch("scheduler.api.history.get_db", return_value=_FakeDB([])):
        resp = client.get("/history/?paged=true&cursor=not-valid-base64!!", headers=_auth_headers())
    assert resp.status_code == 400


def test_paged_history_rejects_invalid_limit():
    with patch("scheduler.api.history.get_db", return_value=_FakeDB([])):
        resp = client.get("/history/?paged=true&limit=not-a-number", headers=_auth_headers())
    assert resp.status_code == 400


def test_paged_history_clamps_limit_to_200():
    runs = [_run(f"r{i}", "prod", _now() - timedelta(minutes=i)) for i in range(3)]
    with patch("scheduler.api.history.get_db", return_value=_FakeDB(runs)):
        resp = client.get("/history/?paged=true&limit=10000", headers=_auth_headers())
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


def test_cursor_round_trips_through_encode_decode():
    from scheduler.api.history import _decode_cursor, _encode_cursor

    ts = _now()
    cursor = _encode_cursor(ts, "run-42")
    decoded_ts, decoded_id = _decode_cursor(cursor)
    assert decoded_id == "run-42"
    assert decoded_ts == ts


def test_decode_cursor_rejects_garbage_without_crashing():
    from scheduler.api.history import _decode_cursor

    with pytest.raises(Exception):
        _decode_cursor(base64.urlsafe_b64encode(json.dumps({"nope": True}).encode()).decode())
