"""Run-time job params -> environment variables.

The convention, shared with the Go worker (go-worker/internal/executor
buildEnv) and pinned by tests/fixtures/param_env_contract.json: a param
``FOO=bar`` becomes the environment variable ``FOO=bar``, overriding a
same-named ``executor.env`` entry. No prefix is added; scheduler-injected
context such as ``HYDRA_EXECUTION_DATE`` is just a param whose key starts with
``HYDRA_``.
"""

from typing import Any, Dict, Mapping, Optional


def merge_param_env(executor_env: Optional[Mapping[str, Any]], params: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Return executor env overlaid with params, all values as strings."""
    merged: Dict[str, str] = {k: str(v) for k, v in (executor_env or {}).items()}
    merged.update({k: str(v) for k, v in (params or {}).items()})
    return merged


def inject_params(job: Dict[str, Any], params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a copy of ``job`` whose executor env includes ``params``.

    ``job`` is returned unchanged when there are no params.
    """
    if not params:
        return job
    job = dict(job)
    executor = dict(job.get("executor") or {})
    executor["env"] = merge_param_env(executor.get("env"), params)
    job["executor"] = executor
    return job
