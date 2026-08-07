"""Fast fail-first checks: is there even a deployment here to test?"""

import pytest

from ._client import ApiError, Client
from ._config import SKIP_REASON, enabled
from ._domains import create_domain, delete_domain, random_domain_name

pytestmark = pytest.mark.skipif(not enabled(), reason=SKIP_REASON)


def test_health_endpoint_ok(config):
    import urllib.request

    with urllib.request.urlopen(f"{config.api_url}/health", timeout=10) as resp:
        assert resp.status == 200


def test_admin_token_is_valid(admin_client):
    domains = admin_client.get("/admin/domains")
    assert "domains" in domains


def test_domain_lifecycle_create_and_delete(admin_client):
    """The rest of the suite depends entirely on domain provisioning working —
    verify that in isolation before anything else runs."""
    name = random_domain_name("smoke")
    handle = create_domain(admin_client, name)
    try:
        assert handle.token
        assert handle.redis_password
        domains = admin_client.get("/admin/domains")["domains"]
        assert any(d["domain"] == name for d in domains)
    finally:
        delete_domain(admin_client, name)

    domains_after = admin_client.get("/admin/domains")["domains"]
    assert not any(d["domain"] == name for d in domains_after)


def test_invalid_token_is_rejected(config):
    bad = Client(config.api_url, "not-a-real-token")
    with pytest.raises(ApiError) as exc_info:
        bad.get("/jobs/")
    assert exc_info.value.status == 401
