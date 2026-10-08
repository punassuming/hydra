"""Pins the params -> environment rule shared by the Python and Go workers.

The Go side is go-worker/internal/executor/contract_test.go, driven by the
same fixture, so the two implementations cannot drift apart silently.
"""

import json
from pathlib import Path

import pytest

from worker.utils.params import inject_params, merge_param_env

FIXTURE = Path(__file__).parent / "fixtures" / "param_env_contract.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_merge_param_env_matches_contract(case):
    assert merge_param_env(case["executor_env"], case["params"]) == case["expected_env"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_inject_params_applies_contract_to_job(case):
    job = {"executor": {"type": "shell", "script": "true", "env": dict(case["executor_env"])}}
    result = inject_params(job, case["params"])
    assert result["executor"]["env"] == case["expected_env"]


def test_inject_params_does_not_mutate_the_input_job():
    job = {"executor": {"type": "shell", "env": {"A": "1"}}}
    inject_params(job, {"B": "2"})
    assert job["executor"]["env"] == {"A": "1"}


def test_inject_params_without_params_returns_job_unchanged():
    job = {"executor": {"type": "shell"}}
    assert inject_params(job, None) is job
    assert inject_params(job, {}) is job


def test_python_side_coerces_non_string_values():
    """The API only accepts strings, but internal producers may not; Python
    stringifies (Go is typed map[string]string and never sees non-strings)."""
    assert merge_param_env({}, {"N": 3, "B": True}) == {"N": "3", "B": "True"}


def test_no_hydra_param_prefix_is_ever_injected():
    assert all(not k.startswith("HYDRA_PARAM_") for k in merge_param_env({}, {"FOO": "bar"}))
