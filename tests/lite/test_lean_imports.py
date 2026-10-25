"""The lite edition must run on the lean dependency set: no Redis, MongoDB, AI SDKs or SQLAlchemy.

Runs in a subprocess so earlier tests (which import the full scheduler) cannot pollute ``sys.modules``.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[2]
HEAVY = ["redis", "pymongo", "openai", "google.genai", "cryptography", "sqlalchemy", "sse_starlette", "dotenv", "bson"]


def _modules(pattern_dirs):
    names = []
    for d in pattern_dirs:
        for f in sorted((ROOT / d).rglob("*.py")):
            rel = f.relative_to(ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts[-1] != "__main__":  # importing a __main__ module would run it (the worker's loops forever)
                names.append(".".join(parts))
    return names


def test_lite_cli_and_shared_modules_import_without_the_full_extra():
    lite = _modules(["hydra_lite"])
    shared = [
        "cli.__main__",
        "cli._client",
        "scheduler.models.job_definition",
        "scheduler.models.job_run",
        "scheduler.models.worker_info",
        "scheduler.models.run_params",
        "scheduler.utils.schedule",
        "scheduler.utils.post_run",
        "scheduler.utils.retry",
        "scheduler.utils.notifications",
        "scheduler.utils.job_validation",
        "scheduler.utils.affinity",
        "scheduler.utils.modes",
        "worker.executor",
        "worker.runtime",
        "worker.protocol",
        "worker.windows_tasks",
        "worker.utils.completion",
        "worker.utils.params",
    ]
    code = textwrap.dedent(
        f"""
        import importlib, sys
        failures = []
        for name in {lite + shared!r}:
            try:
                importlib.import_module(name)
            except Exception as exc:  # report every offender, not just the first
                failures.append(f"{{name}}: {{type(exc).__name__}}: {{exc}}")
        leaked = [m for m in {HEAVY!r} if m in sys.modules or any(k == m or k.startswith(m + '.') for k in sys.modules)]
        print("FAILURES", failures)
        print("LEAKED", leaked)
        """
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=dict(os.environ),
    )
    assert "FAILURES []" in out.stdout and "LEAKED []" in out.stdout, out.stdout + out.stderr
