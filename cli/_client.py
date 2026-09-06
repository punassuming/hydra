"""Small, dependency-free HTTP client for the Hydra API."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from typing import Any


class APIError(RuntimeError):
    """A request rejected by Hydra or the network layer."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        *,
        body: Any = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.method = method
        self.path = path


class HydraClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        domain: str | None = None,
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["x-api-key"] = token
        if domain:
            self.headers["x-domain"] = domain

    # These small lifecycle helpers are intentionally shared by hydra-ctl and
    # constrained integrations.  Keep policy (such as manifest allowlisting)
    # outside this transport client.
    def validate(self, job: Mapping[str, Any]) -> Any:
        return self.request("POST", "/jobs/validate", body=job)

    def submit(self, job: Mapping[str, Any]) -> Any:
        return self.request("POST", "/jobs/", body=job)

    def run(self, job_id: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("POST", f"/jobs/{job_id}/run", body={"params": dict(params or {})})

    def logs(self, run_id: str) -> Any:
        return self.request("GET", f"/runs/{run_id}")

    def history(self) -> Any:
        return self.request("GET", "/history/")

    def cancel(self, run_id: str) -> Any:
        return self.request("POST", f"/runs/{run_id}/kill", body={})

    def rotate_token(self) -> Any:
        return self.request("POST", "/domain/token/rotate", body={})

    def run_details(self, run_id: str) -> Any:
        return self.request("GET", f"/runs/{run_id}")

    def job_runs(self, job_id: str) -> Any:
        return self.request("GET", f"/jobs/{job_id}/runs")

    def workers(self) -> Any:
        return self.request("GET", "/workers/")

    def health(self) -> Any:
        return self.request("GET", "/health")

    def overview(self, view: str) -> Any:
        return self.request("GET", f"/overview/{view}")

    def set_worker_state(self, worker_id: str, state: str) -> Any:
        return self.request("POST", f"/workers/{worker_id}/state", body={"state": state})

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: Mapping[str, Any] | None = None,
    ) -> Any:
        url = self._url(path, query)
        headers = dict(self.headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                if not payload:
                    return None
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, method=method, path=path) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise APIError(f"could not reach {self.base_url}: {reason}") from exc

    def stream_sse(self, path: str) -> Iterator[tuple[str, Any]]:
        request = urllib.request.Request(self._url(path), headers={**self.headers, "Accept": "text/event-stream"})
        try:
            with urllib.request.urlopen(request, timeout=None) as response:
                event = "message"
                data: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data:
                            payload = "\n".join(data)
                            try:
                                payload = json.loads(payload)
                            except json.JSONDecodeError:
                                pass
                            yield event, payload
                        event, data = "message", []
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                if data:
                    payload = "\n".join(data)
                    try:
                        payload = json.loads(payload)
                    except json.JSONDecodeError:
                        pass
                    yield event, payload
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, method="GET", path=path) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise APIError(f"could not reach {self.base_url}: {reason}") from exc

    def _url(self, path: str, query: Mapping[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            clean = {key: value for key, value in query.items() if value is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError, *, method: str | None = None, path: str | None = None) -> APIError:
        detail = exc.reason
        body: Any = None
        try:
            payload = json.loads(exc.read())
            body = payload
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return APIError(f"API returned {exc.code}: {detail}", exc.code, body=body, method=method, path=path)
