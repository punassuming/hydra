"""Constrained OpenClaw facade over Hydra's shared control-plane client."""

from typing import Any

from cli._client import APIError as HydraError
from cli._client import HydraClient as _HydraClient

class HydraClient(_HydraClient):
    """API client whose token and domain are fixed for its entire lifetime."""

    def __init__(self, base_url: str, token: str, domain: str, timeout: float = 30.0):
        if not token or not domain:
            raise ValueError("token and domain are required")
        self.token, self.domain = token, domain
        super().__init__(base_url, token=token, domain=domain, timeout=timeout)

    def request(self, method: str, path: str, body: Any = None) -> Any:
        return super().request(method, path, body=body)
