"""Chaos-style resilience checks: does the system actually recover from the
failures a home-lab is likely to hit — a worker dying mid-job, Redis or
Mongo restarting?

Docker backend only. Each test additionally requires the specific container
name(s) it acts on (ACCEPTANCE_DOCKER_REDIS_CONTAINER /
ACCEPTANCE_DOCKER_MONGO_CONTAINER) since those aren't containers this suite
creates itself — they're part of the main stack under test.
"""

import time

import pytest

from ._config import SKIP_REASON, enabled
from ._domains import wait_for_worker_online
from ._infra import wait_until
from ._jobs import submit_and_wait, wait_for_terminal_run

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


@pytest.fixture(autouse=True)
def _require_docker_backend(config):
    if config.backend != "docker":
        pytest.skip("resilience checks require ACCEPTANCE_BACKEND=docker")


def test_worker_failover_reassigns_a_job_killed_mid_run(domain_factory, infra, config):
    domain = domain_factory()
    survivor = f"hydra-accept-{domain.name}-survivor"
    victim = f"hydra-accept-{domain.name}-victim"
    for name in (survivor, victim):
        infra.start_worker(
            name=name, domain=domain.name, api_token=domain.token,
            redis_url=config.docker_redis_url, redis_password=domain.redis_password,
            tags="acceptance", flavor="python", max_concurrency=config.docker_max_concurrency,
        )
    domain.worker_names.extend([survivor, victim])
    wait_for_worker_online(domain.client, timeout=config.timeout_seconds)
    workers = domain.client.get("/workers/")
    assert len(workers) == 2, f"expected both workers registered before starting the chaos test: {workers}"

    job = domain.client.post(
        "/jobs/",
        {
            "name": "failover-check",
            "executor": {"type": "shell", "shell": "bash", "script": "sleep 8 && echo survived"},
            "timeout": 60,
        },
    )
    job_id = job.get("_id") or job.get("id")

    def _is_running():
        runs = domain.client.get(f"/jobs/{job_id}/runs")
        return bool(runs) and runs[0].get("status") == "running"

    wait_until(_is_running, timeout=15, interval=0.5, description="the job to start running")
    running_worker = domain.client.get(f"/jobs/{job_id}/runs")[0].get("worker_id")
    assert running_worker in (survivor, victim)
    other_worker = survivor if running_worker == victim else victim

    # Hard-kill (not a graceful stop) the worker currently running the job —
    # the realistic failure mode (crash, OOM-kill, node reboot), not a clean shutdown.
    infra.kill_container(running_worker)

    # Heartbeat TTL (default 10s) + failover_loop's own poll cadence (2s) +
    # re-dispatch + the job's own runtime, with slack for slower hardware.
    latest = wait_for_terminal_run(domain.client, job_id, timeout=max(90, config.timeout_seconds))
    assert latest.get("status") == "success", (
        f"job did not recover after its worker was killed: {latest}"
    )
    assert latest.get("worker_id") == other_worker, (
        f"expected the surviving worker '{other_worker}' to pick up the failed-over job, "
        f"got '{latest.get('worker_id')}'"
    )


def test_redis_restart_self_heals_without_a_scheduler_restart(domain_factory, infra, config):
    if not config.docker_redis_container:
        pytest.skip("set ACCEPTANCE_DOCKER_REDIS_CONTAINER to exercise the Redis-restart resilience check")

    domain = domain_factory(with_worker=True)

    baseline = submit_and_wait(
        domain.client,
        {"name": "pre-restart-check", "executor": {"type": "shell", "shell": "bash", "script": "echo before"}, "timeout": 30},
        timeout=config.timeout_seconds,
    )
    assert baseline.get("status") == "success", "sanity check before the chaos step failed — nothing to recover from"

    # Redis ACL users are in-memory only (no aclfile configured), so this wipes
    # every domain's worker ACL user until scheduler.redis_acl_reconciliation_loop
    # re-applies them (default interval: 30s — see SCHEDULER_ACL_RECONCILE_INTERVAL).
    infra.restart_container(config.docker_redis_container)

    def _post_restart_job_succeeds():
        payload = {
            "name": f"post-restart-check-{int(time.time())}",
            "executor": {"type": "shell", "shell": "bash", "script": "echo after"},
            "timeout": 30,
        }
        run = submit_and_wait(domain.client, payload, timeout=15, poll_interval=1.0)
        return run.get("status") == "success"

    # Generous window: reconcile-loop interval (default 30s) + worker reconnect/re-auth + one job's runtime.
    wait_until(
        _post_restart_job_succeeds,
        timeout=max(90, config.timeout_seconds),
        interval=5,
        description="worker Redis auth to self-heal after a Redis restart",
    )


def test_mongo_restart_does_not_break_job_persistence(domain_factory, infra, config):
    if not config.docker_mongo_container:
        pytest.skip("set ACCEPTANCE_DOCKER_MONGO_CONTAINER to exercise the Mongo-restart resilience check")

    domain = domain_factory(with_worker=True)
    infra.restart_container(config.docker_mongo_container)

    def _job_after_mongo_restart_succeeds():
        payload = {
            "name": f"post-mongo-restart-{int(time.time())}",
            "executor": {"type": "shell", "shell": "bash", "script": "echo ok"},
            "timeout": 30,
        }
        run = submit_and_wait(domain.client, payload, timeout=15, poll_interval=1.0)
        return run.get("status") == "success"

    wait_until(
        _job_after_mongo_restart_succeeds,
        timeout=max(60, config.timeout_seconds),
        interval=3,
        description="job submission/persistence to recover after a Mongo restart",
    )
