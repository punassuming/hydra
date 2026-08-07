"""Exercise every executor type the deployment claims to support.

Requires a domain with an online worker. On the docker backend one is
provisioned automatically; on kubectl/none backends set
ACCEPTANCE_EXISTING_DOMAIN + ACCEPTANCE_EXISTING_TOKEN to point at a domain
that already has a worker running.
"""

import pytest

from ._client import Client
from ._config import SKIP_REASON, enabled
from ._jobs import submit_and_wait
from .job_matrix import JOB_MATRIX, MARKER

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


@pytest.fixture
def matrix_client(config, domain_factory):
    """Prefer a freshly provisioned domain+worker (docker backend). Falls
    back to ACCEPTANCE_EXISTING_DOMAIN/TOKEN when the backend can't
    provision one (kubectl/none) — checked *before* touching domain_factory,
    since domain_factory(with_worker=True) itself skips on non-docker
    backends and would otherwise pre-empt this fallback."""
    if config.backend != "docker":
        if config.existing_domain and config.existing_token:
            return Client(config.api_url, config.existing_token, domain=config.existing_domain)
        pytest.skip(
            "no worker available to run the executor matrix against: set ACCEPTANCE_BACKEND=docker, "
            "or ACCEPTANCE_EXISTING_DOMAIN + ACCEPTANCE_EXISTING_TOKEN for an already-running domain"
        )
    return domain_factory(with_worker=True).client


@pytest.mark.parametrize("spec", JOB_MATRIX, ids=[s.key for s in JOB_MATRIX])
def test_executor(spec, matrix_client, config):
    reason = spec.unavailable_reason(config)
    if reason:
        pytest.skip(reason)

    payload = spec.build(config)
    run = submit_and_wait(matrix_client, payload, timeout=config.timeout_seconds)

    assert run.get("status") == "success", (
        f"{spec.label} did not succeed: status={run.get('status')} "
        f"returncode={run.get('returncode')} stderr={run.get('stderr')!r}"
    )
    if spec.expect_marker_in_output:
        output = f"{run.get('stdout', '')}\n{run.get('stdout_tail', '')}"
        assert MARKER in output, f"{spec.label}: expected marker not found in stdout: {output!r}"
