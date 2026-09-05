from scheduler.utils.redis_acl import (
    worker_acl_channel_patterns,
    worker_acl_commands,
)


def test_worker_acl_allows_heartbeat_registration_and_kill_listener():
    commands = worker_acl_commands()
    assert "+hexists" in commands
    assert "+subscribe" in commands

    assert worker_acl_channel_patterns("prod") == ["&job_kill:prod"]

