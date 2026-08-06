"""Backend drivers for the parts of the acceptance suite that need to touch
infrastructure directly (spin up a throwaway worker container, restart Redis,
kill a worker mid-job) rather than just calling the scheduler's HTTP API.

Two real backends:

- ``DockerInfra`` — for ``ACCEPTANCE_BACKEND=docker``. Fully self-provisioning:
  builds the worker images if needed and launches/tears down throwaway worker
  containers via plain ``docker run`` (not ``docker compose``, so each
  container can carry its own independent DOMAIN/API_TOKEN/tags without
  fighting over a single compose service definition). Requires
  ACCEPTANCE_DOCKER_NETWORK to be set to the network your main stack's
  scheduler/redis containers are already on.

- ``KubectlInfra`` — for ``ACCEPTANCE_BACKEND=kubectl``. Does NOT create new
  Deployments — the Helm chart is the source of truth for what's installed.
  Only restarts/scales resources that already exist.

``NullInfra`` backs ``ACCEPTANCE_BACKEND=none``; every method raises so a
test that needs infra access fails loudly if accidentally invoked instead of
being skipped (callers should check ``config.backend`` and skip explicitly).
"""

import subprocess
import time
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]


class InfraError(RuntimeError):
    pass


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT, **kwargs)
    if result.returncode != 0:
        raise InfraError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


class DockerInfra:
    IMAGE_TAGS = {"python": "hydra-acceptance-worker:python", "go": "hydra-acceptance-worker:go"}
    DOCKERFILES = {"python": ("worker/Dockerfile", "."), "go": ("go-worker/Dockerfile", "go-worker")}

    def __init__(self, network: str):
        if not network:
            raise InfraError(
                "ACCEPTANCE_DOCKER_NETWORK is required for ACCEPTANCE_BACKEND=docker — "
                "find it with: docker inspect <your-redis-container> "
                "--format '{{json .NetworkSettings.Networks}}'"
            )
        self.network = network
        self._built = set()

    def ensure_image(self, flavor: str) -> str:
        tag = self.IMAGE_TAGS[flavor]
        if tag in self._built:
            return tag
        dockerfile, context = self.DOCKERFILES[flavor]
        _run(["docker", "build", "-f", dockerfile, "-t", tag, context])
        self._built.add(tag)
        return tag

    def start_worker(
        self,
        *,
        name: str,
        domain: str,
        api_token: str,
        redis_url: str,
        redis_password: str,
        tags: str,
        flavor: str,
        max_concurrency: int,
        require_acl: bool = True,
    ) -> None:
        image = self.ensure_image(flavor)
        self.stop_worker(name)  # idempotent: clear out any stale container with the same name
        cmd = [
            "docker", "run", "-d",
            "--name", name,
            "--hostname", name,
            "--network", self.network,
            "--label", "hydra-acceptance=1",
            "-e", f"WORKER_ID={name}",
            "-e", f"DOMAIN={domain}",
            "-e", f"API_TOKEN={api_token}",
            "-e", f"REDIS_URL={redis_url}",
            "-e", f"REDIS_PASSWORD={redis_password}",
            "-e", f"WORKER_REQUIRE_REDIS_ACL={'true' if require_acl else 'false'}",
            "-e", f"WORKER_TAGS={tags}",
            "-e", f"MAX_CONCURRENCY={max_concurrency}",
            "-e", "DEPLOYMENT_TYPE=acceptance",
            image,
        ]
        _run(cmd)

    def stop_worker(self, name: str) -> None:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, cwd=REPO_ROOT)

    def restart_container(self, name: str) -> None:
        _run(["docker", "restart", name])

    def kill_container(self, name: str) -> None:
        _run(["docker", "kill", name])

    def container_running(self, name: str) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def cleanup_all_acceptance_containers(self) -> None:
        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=hydra-acceptance=1"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        ids = [line for line in result.stdout.splitlines() if line.strip()]
        if ids:
            subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, text=True, cwd=REPO_ROOT)


class KubectlInfra:
    def __init__(self, namespace: str):
        self.namespace = namespace

    def restart_statefulset(self, name: str, wait_timeout: str = "120s") -> None:
        _run(["kubectl", "-n", self.namespace, "rollout", "restart", f"statefulset/{name}"])
        _run(["kubectl", "-n", self.namespace, "rollout", "status", f"statefulset/{name}", f"--timeout={wait_timeout}"])

    def restart_deployment(self, name: str, wait_timeout: str = "120s") -> None:
        _run(["kubectl", "-n", self.namespace, "rollout", "restart", f"deployment/{name}"])
        _run(["kubectl", "-n", self.namespace, "rollout", "status", f"deployment/{name}", f"--timeout={wait_timeout}"])

    def delete_pod(self, pod_name: str) -> None:
        _run(["kubectl", "-n", self.namespace, "delete", "pod", pod_name, "--wait=false"])

    def pods_for_deployment(self, deployment_name: str) -> List[str]:
        result = _run([
            "kubectl", "-n", self.namespace, "get", "pods",
            "-l", f"app.kubernetes.io/instance={deployment_name.split('-worker-')[0]}",
            "-o", "jsonpath={.items[*].metadata.name}",
        ])
        return [p for p in result.stdout.split() if deployment_name in p]

    def wait_for_deployment_ready(self, name: str, timeout: str = "120s") -> None:
        _run(["kubectl", "-n", self.namespace, "rollout", "status", f"deployment/{name}", f"--timeout={timeout}"])


class NullInfra:
    def __getattr__(self, item):
        def _unavailable(*_args, **_kwargs):
            raise InfraError(
                f"infra operation '{item}' requires ACCEPTANCE_BACKEND=docker or kubectl "
                "(current backend is 'none' — this test should have been skipped)"
            )
        return _unavailable


def get_infra(config):
    if config.backend == "docker":
        return DockerInfra(config.docker_network)
    if config.backend == "kubectl":
        return KubectlInfra(config.k8s_namespace)
    return NullInfra()


def wait_until(predicate, timeout: float, interval: float = 1.0, description: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    last_exc: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # noqa: BLE001 - deliberately broad, re-raised as timeout below
            last_exc = exc
        time.sleep(interval)
    detail = f" (last error: {last_exc})" if last_exc else ""
    raise TimeoutError(f"timed out waiting for {description}{detail}")
