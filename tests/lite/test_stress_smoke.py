"""Opt-in stress smoke test: ``HYDRA_STRESS=1 uv run pytest tests/lite/test_stress_smoke.py``.

Drives scripts/lite_stress.py's smoke profile against a real daemon with real worker processes (Linux only: it reads
/proc). Takes a couple of minutes, so it never runs in default CI. See the script's docstring for the full profile.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("HYDRA_STRESS") != "1" or not sys.platform.startswith("linux"),
    reason="set HYDRA_STRESS=1 (Linux) to run the stress smoke test",
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lite_stress.py"


@pytest.fixture(scope="module")
def stress():
    spec = importlib.util.spec_from_file_location("lite_stress", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lite_stress"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("scenario", ["burst", "schedules", "overload", "history", "logs", "chaos"])
def test_scenario_holds_its_invariants(stress, scenario):
    result = stress.SCENARIOS[scenario](dict(stress.PROFILES["smoke"]))
    assert result["violations"] == [], result
