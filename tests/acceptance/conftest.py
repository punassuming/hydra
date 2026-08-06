import urllib.error
import urllib.request

import pytest

from ._client import Client
from ._config import CONFIG, SKIP_REASON, enabled
from ._domains import DomainHandle, create_domain, delete_domain, random_domain_name, wait_for_worker_online
from ._infra import get_infra


def pytest_collection_modifyitems(config, items):
    if enabled():
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if "acceptance" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def config():
    return CONFIG


@pytest.fixture(scope="session", autouse=True)
def _fail_fast_if_unreachable(config):
    """Give a clear, immediate error instead of confusing per-test timeouts
    if the target scheduler simply isn't reachable."""
    if not enabled():
        return
    try:
        with urllib.request.urlopen(f"{config.api_url}/health", timeout=10) as resp:
            if resp.status != 200:
                pytest.exit(f"Scheduler at {config.api_url} returned HTTP {resp.status} for /health", returncode=1)
    except (OSError, urllib.error.URLError) as exc:
        pytest.exit(f"Scheduler at {config.api_url} is not reachable: {exc}", returncode=1)


@pytest.fixture(scope="session")
def admin_client(config):
    return Client(config.api_url, config.admin_token)


@pytest.fixture(scope="session")
def infra(config):
    return get_infra(config)


@pytest.fixture
def domain_factory(admin_client, infra, config):
    """Yields a callable that provisions a fresh throwaway domain — and, on
    the docker backend, a matching worker — then tears everything down
    (unless ACCEPTANCE_KEEP=1)."""
    created = []

    def _make(
        *,
        with_worker: bool = False,
        flavor: str = "python",
        tags: str = "acceptance",
        name: str | None = None,
        wait_online: bool = True,
    ) -> DomainHandle:
        domain_name = name or random_domain_name()
        handle = create_domain(admin_client, domain_name)
        created.append(handle)
        if with_worker:
            if config.backend != "docker":
                pytest.skip(
                    f"provisioning a worker automatically requires ACCEPTANCE_BACKEND=docker "
                    f"(current backend: '{config.backend}')"
                )
            worker_name = f"hydra-accept-{domain_name}-{flavor}"
            infra.start_worker(
                name=worker_name,
                domain=domain_name,
                api_token=handle.token,
                redis_url=config.docker_redis_url,
                redis_password=handle.redis_password,
                tags=tags,
                flavor=flavor,
                max_concurrency=config.docker_max_concurrency,
            )
            handle.worker_names.append(worker_name)
            if wait_online:
                wait_for_worker_online(handle.client, timeout=config.timeout_seconds)
        return handle

    yield _make

    if config.keep:
        return
    for handle in created:
        if config.backend == "docker":
            for worker_name in handle.worker_names:
                try:
                    infra.stop_worker(worker_name)
                except Exception:
                    pass
        delete_domain(admin_client, handle.name)


@pytest.fixture
def acceptance_domain(domain_factory):
    """The common case: one fresh domain with one worker already online."""
    return domain_factory(with_worker=True)
