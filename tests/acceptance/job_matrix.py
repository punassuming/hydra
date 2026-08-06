"""Predefined jobs covering every executor type, for the acceptance suite's
executor-matrix test. Each spec knows how to build its own JobCreate payload
and whether it's currently runnable (some need optional config: a real SQL
target, an external binary known to exist on the worker host).

http/sensor targets point at the scheduler's own /health endpoint rather than
an external service, so the matrix has no dependency beyond the deployment
under test itself.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional

from ._config import AcceptanceConfig

MARKER = "hydra-acceptance-ok"


@dataclass
class JobSpec:
    key: str
    label: str
    build: Callable[[AcceptanceConfig], dict]
    unavailable_reason: Callable[[AcceptanceConfig], Optional[str]]
    expect_marker_in_output: bool = True


def _shell(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-shell",
        "tags": ["acceptance"],
        "executor": {"type": "shell", "shell": "bash", "script": f"echo {MARKER}"},
        "timeout": 30,
    }


def _python(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-python",
        "tags": ["acceptance"],
        "executor": {"type": "python", "code": f"print('{MARKER}')"},
        "timeout": 60,
    }


def _http(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-http",
        "tags": ["acceptance"],
        "executor": {
            "type": "http",
            "method": "GET",
            "url": f"{config.internal_api_url}/health",
            "expected_status": [200],
            "timeout_seconds": 15,
        },
        "timeout": 30,
    }


def _sensor(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-sensor",
        "tags": ["acceptance"],
        "executor": {
            "type": "sensor",
            "sensor_type": "http",
            "target": f"{config.internal_api_url}/health",
            "poll_interval_seconds": 2,
            "timeout_seconds": 30,
            "expected_status": [200],
        },
        "timeout": 60,
    }


def _external(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-external",
        "tags": ["acceptance"],
        "executor": {"type": "external", "command": config.external_binary, "args": list(config.external_args)},
        "timeout": 30,
    }


def _sql(config: AcceptanceConfig) -> dict:
    return {
        "name": "acceptance-sql",
        "tags": ["acceptance"],
        "executor": {
            "type": "sql",
            "dialect": config.sql_dialect,
            "connection_uri": config.sql_connection_uri,
            "query": "SELECT 1",
            "max_rows": 1,
        },
        "timeout": 30,
    }


def _sql_unavailable(config: AcceptanceConfig) -> Optional[str]:
    if not config.sql_connection_uri:
        return "set ACCEPTANCE_SQL_CONNECTION_URI to exercise the sql executor"
    return None


def _external_unavailable(config: AcceptanceConfig) -> Optional[str]:
    if not config.test_external:
        return "set ACCEPTANCE_TEST_EXTERNAL=1 to exercise the external executor"
    return None


def _always_available(config: AcceptanceConfig) -> Optional[str]:
    return None


# "external" doesn't echo the marker through job stdout the same predictable way
# across platforms (it runs a raw binary, not a shell), so don't require the
# marker check for it — success/exit-code is the meaningful signal there.
JOB_MATRIX: List[JobSpec] = [
    JobSpec("shell", "shell executor", _shell, _always_available),
    JobSpec("python", "python executor", _python, _always_available),
    JobSpec("http", "http executor (self-target: /health)", _http, _always_available, expect_marker_in_output=False),
    JobSpec("sensor", "sensor executor (self-target: /health)", _sensor, _always_available, expect_marker_in_output=False),
    JobSpec("external", "external executor", _external, _external_unavailable, expect_marker_in_output=False),
    JobSpec("sql", "sql executor", _sql, _sql_unavailable, expect_marker_in_output=False),
]
