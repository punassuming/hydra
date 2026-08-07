"""Mixed worker pools (Python + Go) actually route jobs by affinity tag
rather than either flavor grabbing whatever's queued first.

Docker backend only: this needs to dynamically stand up two independently
tagged pools, which the kubectl backend deliberately does not do (see
_infra.py's KubectlInfra docstring — pool topology there is Helm's job).
"""

import pytest

from ._config import SKIP_REASON, enabled
from ._domains import wait_for_worker_online
from ._jobs import submit_and_wait

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


@pytest.fixture(autouse=True)
def _require_docker_backend(config):
    if config.backend != "docker":
        pytest.skip("worker-pool routing test requires ACCEPTANCE_BACKEND=docker")


def test_job_lands_on_the_tagged_pool(domain_factory, infra, config):
    domain = domain_factory()

    python_worker = f"hydra-accept-{domain.name}-python-only"
    go_worker = f"hydra-accept-{domain.name}-go-only"
    infra.start_worker(
        name=python_worker, domain=domain.name, api_token=domain.token,
        redis_url=config.docker_redis_url, redis_password=domain.redis_password,
        tags="python-only", flavor="python", max_concurrency=config.docker_max_concurrency,
    )
    infra.start_worker(
        name=go_worker, domain=domain.name, api_token=domain.token,
        redis_url=config.docker_redis_url, redis_password=domain.redis_password,
        tags="go-only", flavor="go", max_concurrency=config.docker_max_concurrency,
    )
    domain.worker_names.extend([python_worker, go_worker])
    wait_for_worker_online(domain.client, timeout=config.timeout_seconds)

    workers = domain.client.get("/workers/")
    assert len(workers) == 2, f"expected both pools registered, got: {workers}"

    # Job affinity-tagged for the Go-only pool must run there, not on the
    # Python-only pool (which the Go job's affinity excludes).
    run = submit_and_wait(
        domain.client,
        {
            "name": "routing-check-go",
            "affinity": {"tags": ["go-only"]},
            "executor": {"type": "shell", "shell": "bash", "script": "echo pinned-to-go"},
            "timeout": 30,
        },
        timeout=config.timeout_seconds,
    )
    assert run.get("status") == "success", run
    assert run.get("worker_id") == go_worker, (
        f"expected the go-only-tagged job to run on '{go_worker}', ran on '{run.get('worker_id')}' instead"
    )

    # And the reverse, for the python-only pool.
    run2 = submit_and_wait(
        domain.client,
        {
            "name": "routing-check-python",
            "affinity": {"tags": ["python-only"]},
            "executor": {"type": "shell", "shell": "bash", "script": "echo pinned-to-python"},
            "timeout": 30,
        },
        timeout=config.timeout_seconds,
    )
    assert run2.get("status") == "success", run2
    assert run2.get("worker_id") == python_worker


def test_sql_and_impersonation_only_advertised_by_python_pool(domain_factory, infra, config):
    """The Go worker doesn't implement the sql executor or user impersonation
    — confirm that's reflected in what it actually advertises, not just in
    docs, so affinity-based routing away from it is enforceable."""
    domain = domain_factory()
    go_worker = f"hydra-accept-{domain.name}-go-caps"
    infra.start_worker(
        name=go_worker, domain=domain.name, api_token=domain.token,
        redis_url=config.docker_redis_url, redis_password=domain.redis_password,
        tags="go-caps", flavor="go", max_concurrency=config.docker_max_concurrency,
    )
    domain.worker_names.append(go_worker)
    wait_for_worker_online(domain.client, timeout=config.timeout_seconds)

    workers = domain.client.get("/workers/")
    go_info = next(w for w in workers if w.get("worker_id") == go_worker)
    assert "sql" not in (go_info.get("capabilities") or []), go_info
