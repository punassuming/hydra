"""Exercises the repo's Redis usage against a REAL redis-server.

The rest of the suite uses hand-rolled fakes, which cannot notice a redis-py
upgrade changing return shapes, decoding, pub/sub messages or ACL behaviour.
These tests start a throwaway server (no persistence, loopback, ephemeral port)
and check exactly the shapes our code unpacks. Skipped when `redis-server` is
not installed; the Compose smoke test covers a real server in CI.
"""

import shutil
import socket
import subprocess
import sys
import time

import pytest
import redis

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("redis-server"), reason="needs a local redis-server binary"
)


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"redis://127.0.0.1:{port}/0"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if redis.from_url(url).ping():
                break
        except redis.exceptions.RedisError:
            time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail("redis-server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def r(server, monkeypatch):
    """The scheduler's own client factory, pointed at the throwaway server."""
    from scheduler import redis_client as scheduler_redis

    for var in ("REDIS_SENTINELS", "REDIS_SENTINEL_MASTER", "REDIS_USERNAME", "REDIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("REDIS_URL", server)
    monkeypatch.setattr(scheduler_redis, "_redis_client", None)
    client = scheduler_redis.get_redis()
    client.flushall()
    yield client
    client.flushall()


def test_client_returns_decoded_python_types(r):
    r.hset("workers:prod:w1", mapping={"state": "online", "current_running": 2})
    assert r.hgetall("workers:prod:w1") == {"state": "online", "current_running": "2"}
    assert r.hincrby("workers:prod:w1", "current_running", 1) == 3

    r.sadd("hydra:domains", "prod", "ml")
    assert r.smembers("hydra:domains") == {"prod", "ml"}

    r.zadd("worker_heartbeats:prod", {"w1": 1700000000.5})
    assert r.zscore("worker_heartbeats:prod", "w1") == 1700000000.5
    assert r.zscore("worker_heartbeats:prod", "missing") is None

    r.rpush("log:history", "a", "b", "c")
    r.ltrim("log:history", -2, -1)
    assert r.lrange("log:history", 0, -1) == ["b", "c"]

    assert r.exists("workers:prod:w1") == 1
    assert r.expire("workers:prod:w1", 100) is True
    assert 0 < r.ttl("workers:prod:w1") <= 100
    assert sorted(r.scan_iter("workers:prod:*")) == ["workers:prod:w1"]
    assert r.delete("workers:prod:w1") == 1
    assert r.hgetall("workers:prod:w1") == {}


def test_bzpopmax_returns_key_member_score_in_priority_order(r):
    # scheduler.py: `key, job_id, _score = r.bzpopmax(pending_keys, timeout=2)`
    r.zadd("job_queue:prod:pending", {"low": 1, "high": 9})
    key, member, score = r.bzpopmax(["job_queue:prod:pending", "job_queue:ml:pending"], timeout=1)
    assert (key, member) == ("job_queue:prod:pending", "high")
    assert float(score) == 9.0
    assert r.bzpopmax(["job_queue:empty:pending"], timeout=1) is None


def test_blpop_returns_queue_and_value_or_none_on_timeout(r):
    # worker.py: `item = r.blpop([queue], timeout=2)`
    r.rpush("job_queue:prod:w1", '{"job_id": "j1"}')
    assert tuple(r.blpop(["job_queue:prod:w1"], timeout=1)) == ("job_queue:prod:w1", '{"job_id": "j1"}')
    assert r.blpop(["job_queue:prod:w1"], timeout=1) is None


def test_pubsub_shapes_used_by_log_stream_and_kill_listener(r):
    pubsub = r.pubsub()
    pubsub.subscribe("job_kill:prod")
    # logs.py: get_message(True, 2.0) with ignore_subscribe_messages -> None until a message arrives.
    assert pubsub.get_message(True, 0.2) is None
    assert r.publish("job_kill:prod", "run-123") == 1
    message = pubsub.get_message(True, 2.0)
    assert message["type"] == "message"
    assert message["data"] == "run-123"  # decoded str; worker.py tolerates bytes too
    assert message["channel"] == "job_kill:prod"
    pubsub.unsubscribe("job_kill:prod")
    pubsub.close()


def test_pubsub_listen_yields_subscribe_then_message_which_the_worker_filters(r):
    # worker.py: `for msg in pubsub.listen(): if msg.get("type") != "message": continue`
    pubsub = r.pubsub()
    pubsub.subscribe("job_kill:prod")
    iterator = pubsub.listen()
    first = next(iterator)
    assert first["type"] == "subscribe"
    r.publish("job_kill:prod", "run-9")
    second = next(iterator)
    assert second["type"] == "message" and second["data"] == "run-9"
    pubsub.close()


def test_acl_lifecycle_through_the_repos_helpers(r, server, monkeypatch):
    """ensure_worker_acl_user / delete_worker_acl_user use execute_command("ACL", ...)."""
    from redis.exceptions import AuthenticationError, NoPermissionError, RedisError

    from scheduler.utils.redis_acl import delete_worker_acl_user, ensure_worker_acl_user
    from worker import redis_client as worker_redis

    info = ensure_worker_acl_user("acme", "s3cret-pw")
    assert info["username"] == "acme" and info["password"] == "s3cret-pw"
    assert "acme" in r.execute_command("ACL", "USERS")

    # A worker connects exactly as the worker does: username = DOMAIN, password = REDIS_PASSWORD.
    monkeypatch.setenv("DOMAIN", "acme")
    monkeypatch.setenv("REDIS_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("REDIS_URL", server)
    monkeypatch.setenv("WORKER_REQUIRE_REDIS_ACL", "true")
    monkeypatch.delenv("REDIS_SENTINELS", raising=False)
    monkeypatch.setattr(worker_redis, "_redis_client", None)
    w = worker_redis.get_redis()
    assert w.ping() is True
    w.hset("workers:acme:w1", mapping={"state": "online"})
    w.rpush("run_events:acme", "{}")
    assert w.publish("log_stream:acme:run-1", "chunk") == 0  # allowed channel (no subscribers)
    w.delete("job_running:acme:j1")

    # ...and is confined to its own domain's keys, commands and channels.
    with pytest.raises(NoPermissionError):
        w.hset("workers:other:w1", mapping={"state": "online"})
    with pytest.raises(NoPermissionError):
        w.get("anything")
    with pytest.raises(NoPermissionError):
        w.publish("log_stream:other:run-1", "chunk")

    assert delete_worker_acl_user("acme") is True
    assert delete_worker_acl_user("acme") is False
    fresh = redis.from_url(server, username="acme", password="s3cret-pw", decode_responses=True)
    with pytest.raises((AuthenticationError, RedisError)):
        fresh.ping()


def test_worker_client_with_wrong_password_is_rejected(r, server, monkeypatch):
    from redis.exceptions import RedisError

    from scheduler.utils.redis_acl import delete_worker_acl_user, ensure_worker_acl_user

    ensure_worker_acl_user("beta", "right-pw")
    try:
        bad = redis.from_url(server, username="beta", password="wrong-pw", decode_responses=True)
        with pytest.raises(RedisError):
            bad.ping()
    finally:
        delete_worker_acl_user("beta")
