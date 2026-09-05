from integrations.external_client.client import HydraClient


def test_client_keeps_domain_and_token_on_every_lifecycle_request(monkeypatch):
    seen = []

    def fake_request(self, method, path, body=None):
        seen.append((method, path, body, self.token, self.domain))
        return {"path": path}

    monkeypatch.setattr(HydraClient, "request", fake_request)
    client = HydraClient("http://hydra", "token-a", "domain-a")
    client.validate({"name": "echo"})
    client.submit({"name": "echo"})
    client.run("job-1", {"x": "1"})
    client.logs("run-1")
    client.history()
    client.cancel("run-1")
    client.rotate_token()

    assert len(seen) == 7
    assert {item[3:] for item in seen} == {("token-a", "domain-a")}
    assert [item[1] for item in seen] == [
        "/jobs/validate",
        "/jobs/",
        "/jobs/job-1/run",
        "/runs/run-1",
        "/history/",
        "/runs/run-1/kill",
        "/domain/token/rotate",
    ]


def test_client_rejects_missing_credentials():
    import pytest

    with pytest.raises(ValueError):
        HydraClient("http://hydra", "", "domain-a")
    with pytest.raises(ValueError):
        HydraClient("http://hydra", "token-a", "")
