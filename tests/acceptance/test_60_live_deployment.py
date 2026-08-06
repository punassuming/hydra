"""Kubectl backend: "point it at your real deployment" checks.

Unlike the docker backend, this deliberately does NOT create or scale any
Deployment — deploy/helm/hydra is the source of truth for what worker pools
exist and which domains they serve. Set ACCEPTANCE_K8S_DOMAINS to the
domain(s) you've already installed via the Helm chart's `workers:` list /
domainSeed.extraDomains, and this verifies the live thing actually works
(and, if you also chaos-test it, actually recovers).

Optionally set ACCEPTANCE_K8S_DOMAIN_TOKENS (same order as
ACCEPTANCE_K8S_DOMAINS) to also exercise real domain-token isolation —
without it, these tests use the admin token with a domain override, which
proves execution works but not token-scoped isolation.
"""

import time

import pytest

from ._client import ApiError, Client
from ._config import SKIP_REASON, enabled
from ._infra import wait_until
from ._jobs import submit_and_wait

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


@pytest.fixture(autouse=True)
def _require_kubectl_backend(config):
    if config.backend != "kubectl":
        pytest.skip("live-deployment checks require ACCEPTANCE_BACKEND=kubectl")
    if not config.k8s_domains:
        pytest.skip("set ACCEPTANCE_K8S_DOMAINS to the domain(s) already installed via the Helm chart")


@pytest.fixture
def domain_clients(config, admin_client):
    """One client per configured domain: a real domain token when provided,
    otherwise the admin token scoped to that domain via the x-domain header."""
    clients = {}
    for i, name in enumerate(config.k8s_domains):
        if i < len(config.k8s_domain_tokens):
            clients[name] = Client(config.api_url, config.k8s_domain_tokens[i], domain=name)
        else:
            clients[name] = admin_client.with_domain(name)
    return clients


def test_each_configured_domain_has_an_online_worker(domain_clients):
    for name, client in domain_clients.items():
        workers = client.get("/workers/")
        online = [w for w in workers if w.get("connectivity_status") == "online"]
        assert online, f"domain '{name}' has no online worker — is its pool installed and healthy?"


def test_job_runs_successfully_on_each_configured_domain(domain_clients, config):
    for name, client in domain_clients.items():
        run = submit_and_wait(
            client,
            {
                "name": f"live-check-{int(time.time())}",
                "executor": {"type": "shell", "shell": "bash", "script": "echo hydra-live-ok"},
                "timeout": 30,
            },
            timeout=config.timeout_seconds,
        )
        assert run.get("status") == "success", f"domain '{name}': {run}"


def test_domain_tokens_are_actually_isolated(config, domain_clients):
    if len(config.k8s_domain_tokens) < 2:
        pytest.skip(
            "set at least 2 entries in ACCEPTANCE_K8S_DOMAIN_TOKENS (matching the first "
            "domains in ACCEPTANCE_K8S_DOMAINS) to verify real token-scoped isolation"
        )
    domain_a, domain_b = config.k8s_domains[0], config.k8s_domains[1]
    client_a, client_b = domain_clients[domain_a], domain_clients[domain_b]

    job = client_a.post(
        "/jobs/",
        {
            "name": f"live-isolation-check-{int(time.time())}",
            "executor": {"type": "shell", "shell": "bash", "script": "true"},
            "schedule": {"mode": "cron", "cron": "0 0 1 1 *", "enabled": False},
        },
    )
    job_id = job.get("_id") or job.get("id")
    with pytest.raises(ApiError) as exc_info:
        client_b.get(f"/jobs/{job_id}")
    assert exc_info.value.status == 403


def test_redis_restart_self_heals_on_the_live_cluster(config, infra, domain_clients):
    if not config.k8s_redis_statefulset:
        pytest.skip("set ACCEPTANCE_K8S_REDIS_STATEFULSET to exercise this against your live cluster")

    infra.restart_statefulset(config.k8s_redis_statefulset)

    def _all_domains_recover():
        for client in domain_clients.values():
            run = submit_and_wait(
                client,
                {
                    "name": f"live-post-restart-{int(time.time())}",
                    "executor": {"type": "shell", "shell": "bash", "script": "echo ok"},
                    "timeout": 30,
                },
                timeout=15,
                poll_interval=1.0,
            )
            if run.get("status") != "success":
                return False
        return True

    wait_until(
        _all_domains_recover,
        timeout=max(120, config.timeout_seconds),
        interval=5,
        description="every configured domain's worker(s) to self-heal after the Redis restart",
    )
