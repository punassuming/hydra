"""End-to-end checks of the SSE endpoints on the real sse-starlette/starlette stack.

Starlette's TestClient buffers responses and cannot consume an infinite stream,
so these run the app on a real uvicorn server (loopback, ephemeral port,
lifespan off so no Redis/Mongo is needed) and stream with httpx. Every wait is
bounded so a regression fails fast instead of hanging.
"""

import json
import queue
import signal
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sse_starlette.sse import AppStatus

from scheduler.api import events as events_api
from scheduler.event_bus import event_bus
from scheduler.main import app

TOKEN = "test-admin-token-sse"
HEADERS = {"x-api-key": TOKEN}


class LiveServer:
    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        config = uvicorn.Config(app, lifespan="off", log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        assert self.server.started, "uvicorn did not start"

    def stop(self, timeout=10.0) -> bool:
        """Request shutdown as SIGTERM would (via handle_exit, which is where
        sse-starlette hooks its graceful drain); True if the thread exited in time."""
        self.server.handle_exit(signal.SIGTERM, None)
        self.thread.join(timeout)
        return not self.thread.is_alive()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(events_api, "_POLL_SECONDS", 0.1)
    # sse-starlette keeps its "server is shutting down" flag process-wide; one
    # test's shutdown must not end the next test's streams.
    AppStatus.should_exit = False
    server = LiveServer()
    server.start()
    yield server
    server.stop()
    server.sock.close()
    AppStatus.should_exit = False


def read_messages(response, wanted, timeout=10.0):
    """Collect `wanted` complete SSE messages as dicts of field -> value."""
    result: "queue.Queue" = queue.Queue()

    def reader():
        messages, current = [], {}
        try:
            for line in response.iter_lines():
                if line == "":
                    if current:
                        messages.append(current)
                        current = {}
                    if len(messages) >= wanted:
                        break
                elif not line.startswith(":") and ":" in line:
                    key, _, value = line.partition(":")
                    current[key] = value.lstrip()
        finally:
            result.put(messages)

    threading.Thread(target=reader, daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        raise AssertionError("timed out waiting for SSE messages") from None


def subscriber_count():
    return len(event_bus._subscribers)


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_events_stream_delivers_published_events_as_named_sse_events(live):
    with httpx.stream("GET", f"{live.url}/events/stream", headers=HEADERS, timeout=10) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert wait_for(lambda: subscriber_count() >= 1)
        event_bus.publish("job_submitted", {"job_id": "j1", "domain": "prod"})
        [message] = read_messages(response, 1)
    assert message["event"] == "job_submitted"
    body = json.loads(message["data"])
    assert body["type"] == "job_submitted" and body["payload"]["job_id"] == "j1"


def test_events_stream_unsubscribes_when_the_client_disconnects(live):
    baseline = subscriber_count()
    with httpx.stream("GET", f"{live.url}/events/stream", headers=HEADERS, timeout=10) as response:
        assert response.status_code == 200
        assert wait_for(lambda: subscriber_count() == baseline + 1)
        event_bus.publish("ping", {"domain": "prod"})
        read_messages(response, 1)
    assert wait_for(lambda: subscriber_count() == baseline), "subscriber was not removed after disconnect"


def test_events_stream_does_not_leak_a_blocked_thread_after_disconnect(live):
    """Regression: the generator blocked in q.get() with no timeout, so every closed
    client left one executor thread parked forever."""
    def parked_readers():
        return [t for t in threading.enumerate() if t.is_alive() and "_next_event" in repr(getattr(t, "_target", ""))]

    for _ in range(3):
        with httpx.stream("GET", f"{live.url}/events/stream", headers=HEADERS, timeout=10) as response:
            assert response.status_code == 200
            assert wait_for(lambda: subscriber_count() >= 1)
            event_bus.publish("ping", {"domain": "prod"})
            read_messages(response, 1)
    assert wait_for(lambda: not parked_readers(), timeout=5), "SSE worker threads are still blocked after clients left"


def test_server_shuts_down_promptly_while_a_stream_is_open(live):
    """sse-starlette 3 changed shutdown handling; an open stream must not block exit."""
    stream = httpx.stream("GET", f"{live.url}/events/stream", headers=HEADERS, timeout=30)
    response = stream.__enter__()
    try:
        assert response.status_code == 200
        assert wait_for(lambda: subscriber_count() >= 1)
        assert live.stop(timeout=10), "uvicorn did not shut down with an SSE stream open"
    finally:
        try:
            stream.__exit__(None, None, None)
        except Exception:
            pass


def test_next_event_returns_none_on_timeout_instead_of_blocking_forever(monkeypatch):
    monkeypatch.setattr(events_api, "_POLL_SECONDS", 0.05)
    started = time.time()
    assert events_api._next_event(queue.Queue()) is None
    assert time.time() - started < 2


def test_events_stream_requires_auth(live):
    assert httpx.get(f"{live.url}/events/stream", timeout=5).status_code in (401, 403)


# ---- /runs/{id}/stream (what the UI's live log view reads) ------------------------------

class _FakePubSub:
    def __init__(self, live_messages):
        self._live = list(live_messages)
        self.subscribed = []
        self.closed = False

    def subscribe(self, channel):
        self.subscribed.append(channel)

    def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
        if self._live:
            return {"type": "message", "data": self._live.pop(0)}
        time.sleep(min(timeout, 0.05))
        return None

    def unsubscribe(self, channel):
        pass

    def close(self):
        self.closed = True


class _FakeRedis:
    def __init__(self, history, live):
        self._history = history
        self.pubsub_obj = _FakePubSub(live)

    def lrange(self, key, start, end):
        return list(self._history)

    def pubsub(self):
        return self.pubsub_obj


class _FakeDb:
    class job_runs:
        @staticmethod
        def find_one(query):
            return {"_id": query["_id"], "domain": "prod"}


def test_run_log_stream_replays_history_then_streams_live_chunks_as_log_chunk(live, monkeypatch):
    from scheduler.api import logs as logs_api

    history = [json.dumps({"text": "old line\n", "stream": "stdout"})]
    live_chunk = json.dumps({"text": "new line\n", "stream": "stderr"})
    fake = _FakeRedis(history=history, live=[live_chunk])
    monkeypatch.setattr(logs_api, "get_redis", lambda: fake)
    monkeypatch.setattr(logs_api, "get_db", lambda: _FakeDb())

    with httpx.stream("GET", f"{live.url}/runs/run-1/stream", headers=HEADERS, timeout=10) as response:
        assert response.status_code == 200
        messages = read_messages(response, 2)
    # The UI listens for the *named* log_chunk event, so the name is part of the contract.
    assert [m["event"] for m in messages] == ["log_chunk", "log_chunk"]
    assert [json.loads(m["data"])["text"] for m in messages] == ["old line\n", "new line\n"]
    assert fake.pubsub_obj.subscribed == ["log_stream:prod:run-1"]
    assert wait_for(lambda: fake.pubsub_obj.closed), "pubsub was not closed after the client disconnected"
