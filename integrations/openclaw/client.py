"""Dependency-free Hydra API client used by the OpenClaw integration."""

import json
import urllib.error
import urllib.request
from typing import Any


class HydraError(RuntimeError):
    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status, self.body, self.method, self.path = status, body, method, path
        super().__init__(f"{method} {path} -> HTTP {status}: {body}")


class HydraClient:
    """API client whose token and domain are fixed for its entire lifetime."""

    def __init__(self, base_url: str, token: str, domain: str, timeout: float = 30.0):
        if not token or not domain:
            raise ValueError("token and domain are required")
        self.base_url, self.token, self.domain, self.timeout = base_url.rstrip("/"), token, domain, timeout

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"x-api-key": self.token, "x-domain": self.domain}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw.decode(errors="replace")
            raise HydraError(exc.code, parsed, method, path) from None

    def validate(self, job: dict) -> Any:
        return self.request("POST", "/jobs/validate", job)

    def submit(self, job: dict) -> Any:
        return self.request("POST", "/jobs/", job)

    def run(self, job_id: str, params: dict | None = None) -> Any:
        return self.request("POST", f"/jobs/{job_id}/run", {"params": params or {}})

    def logs(self, run_id: str) -> Any:
        return self.request("GET", f"/runs/{run_id}")

    def history(self) -> Any:
        return self.request("GET", "/history/")

    def cancel(self, run_id: str) -> Any:
        return self.request("POST", f"/runs/{run_id}/kill", {})

    def rotate_token(self) -> Any:
        """Rotate this domain token; the previous token is revoked immediately.

        This endpoint requires an admin token, so callers should construct a
        separate client with the admin credential for this operation.
        """
        return self.request("POST", "/domain/token/rotate", {})
