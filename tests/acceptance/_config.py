"""Environment-driven configuration for the home-lab acceptance suite.

Every knob has a documented env var (see tests/acceptance/README.md) so the
same suite can point at a throwaway Docker Compose stack, an existing
Kubernetes/Helm deployment, or just a bare API endpoint, without editing code.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def _list_env(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class AcceptanceConfig:
    enabled: bool
    api_url: str
    internal_api_url: str  # how a *worker* reaches the scheduler; differs from api_url when the
    # test runner and the workers are on different networks (e.g. docker backend: the runner
    # hits localhost via a published port, but a worker container reaches "scheduler:8000").
    admin_token: str
    backend: str  # "docker" | "kubectl" | "none"
    timeout_seconds: float
    keep: bool  # skip teardown of anything this run created

    # Docker backend
    docker_network: str
    docker_redis_url: str
    docker_redis_container: str
    docker_mongo_container: str
    docker_scheduler_container: str
    docker_max_concurrency: int

    # Kubectl backend — "bring your own live deployment" mode. The suite does
    # NOT create Helm-managed resources; it points at domains/pools you have
    # already installed via deploy/helm/hydra and verifies them.
    k8s_namespace: str
    k8s_release: str
    k8s_domains: List[str]  # pre-existing domains to exercise
    k8s_domain_tokens: List[str]  # optional, same order as k8s_domains — enables the isolation
    # check in live mode; without these, live-mode tests use the admin token + ?domain= override,
    # which is enough to verify job execution but not real domain-token-scoped isolation.
    k8s_redis_statefulset: str
    k8s_worker_deployments: List[str]  # one or more "<release>-worker-<pool>" names

    # "none" backend / bring-your-own-domain smoke mode
    existing_domain: Optional[str]
    existing_token: Optional[str]

    # Optional executor coverage (skipped unless configured)
    sql_connection_uri: Optional[str]
    sql_dialect: str
    test_external: bool
    external_binary: str
    external_args: List[str] = field(default_factory=list)


def _default_internal_api_url(backend: str, api_url: str, k8s_release: str, k8s_namespace: str) -> str:
    if backend == "docker":
        return "http://scheduler:8000"
    if backend == "kubectl":
        return f"http://{k8s_release}-scheduler.{k8s_namespace}.svc.cluster.local:8000"
    return api_url  # "none" backend: assume runner and worker(s) share one reachable URL


def load_config() -> AcceptanceConfig:
    api_url = os.getenv("ACCEPTANCE_API_URL", "http://localhost:8000").rstrip("/")
    backend = os.getenv("ACCEPTANCE_BACKEND", "none").strip().lower()
    k8s_release = os.getenv("ACCEPTANCE_K8S_RELEASE", "hydra")
    k8s_namespace = os.getenv("ACCEPTANCE_K8S_NAMESPACE", "hydra")
    internal_api_url = os.getenv(
        "ACCEPTANCE_INTERNAL_API_URL",
        _default_internal_api_url(backend, api_url, k8s_release, k8s_namespace),
    ).rstrip("/")
    return AcceptanceConfig(
        enabled=_bool_env("HYDRA_ACCEPTANCE", False),
        api_url=api_url,
        internal_api_url=internal_api_url,
        admin_token=os.getenv("ACCEPTANCE_ADMIN_TOKEN", ""),
        backend=backend,
        timeout_seconds=float(os.getenv("ACCEPTANCE_TIMEOUT_SECONDS", "90")),
        keep=_bool_env("ACCEPTANCE_KEEP", False),
        docker_network=os.getenv("ACCEPTANCE_DOCKER_NETWORK", ""),
        docker_redis_url=os.getenv("ACCEPTANCE_DOCKER_REDIS_URL", "redis://redis:6379/0"),
        docker_redis_container=os.getenv("ACCEPTANCE_DOCKER_REDIS_CONTAINER", ""),
        docker_mongo_container=os.getenv("ACCEPTANCE_DOCKER_MONGO_CONTAINER", ""),
        docker_scheduler_container=os.getenv("ACCEPTANCE_DOCKER_SCHEDULER_CONTAINER", ""),
        docker_max_concurrency=int(os.getenv("ACCEPTANCE_DOCKER_MAX_CONCURRENCY", "2")),
        k8s_namespace=k8s_namespace,
        k8s_release=k8s_release,
        k8s_domains=_list_env("ACCEPTANCE_K8S_DOMAINS"),
        k8s_domain_tokens=_list_env("ACCEPTANCE_K8S_DOMAIN_TOKENS"),
        k8s_redis_statefulset=os.getenv("ACCEPTANCE_K8S_REDIS_STATEFULSET", ""),
        k8s_worker_deployments=_list_env("ACCEPTANCE_K8S_WORKER_DEPLOYMENTS"),
        existing_domain=os.getenv("ACCEPTANCE_EXISTING_DOMAIN") or None,
        existing_token=os.getenv("ACCEPTANCE_EXISTING_TOKEN") or None,
        sql_connection_uri=os.getenv("ACCEPTANCE_SQL_CONNECTION_URI") or None,
        sql_dialect=os.getenv("ACCEPTANCE_SQL_DIALECT", "postgres"),
        test_external=_bool_env("ACCEPTANCE_TEST_EXTERNAL", False),
        external_binary=os.getenv("ACCEPTANCE_EXTERNAL_BINARY", "/bin/echo"),
        external_args=_list_env("ACCEPTANCE_EXTERNAL_ARGS", ["hydra-acceptance-ok"]),
    )


CONFIG = load_config()

SKIP_REASON = "set HYDRA_ACCEPTANCE=1 (and ACCEPTANCE_ADMIN_TOKEN) to run the home-lab acceptance suite"


def enabled() -> bool:
    return CONFIG.enabled and bool(CONFIG.admin_token)
