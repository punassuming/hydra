"""Minimal dependency-free HTTP client for the acceptance suite.

Deliberately mirrors tests/test_end_to_end.py's urllib-based helper rather
than pulling in `requests`, so the suite needs nothing beyond what `tests/`
already depends on.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Optional


class ApiError(RuntimeError):
    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status = status
        self.body = body
        self.method = method
        self.path = path
        super().__init__(f"{method} {path} -> HTTP {status}: {body}")


class Client:
    """A REST client bound to one base URL + auth token (+ optional domain header)."""

    def __init__(self, base_url: str, token: str, domain: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.domain = domain
        self.timeout = timeout

    def with_domain(self, domain: str) -> "Client":
        return Client(self.base_url, self.token, domain=domain, timeout=self.timeout)

    def request(self, method: str, path: str, json_body: Any = None) -> Any:
        data = json.dumps(json_body).encode() if json_body is not None else None
        headers = {"x-api-key": self.token}
        if self.domain:
            headers["x-domain"] = self.domain
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw.decode(errors="replace")
            raise ApiError(exc.code, parsed, method, path) from None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body if body is not None else {})

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, body if body is not None else {})

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)
