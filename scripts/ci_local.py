#!/usr/bin/env python3
"""Run the repo's GitHub Actions CI jobs locally.

The commands are *parsed out of* .github/workflows/python-ci.yml, not copied,
so this runner cannot silently drift from CI. `uses:` steps (checkout,
setup-*, caches) are skipped: it assumes your local toolchains are already
installed. tests/test_workflows.py fails when a CI job is added without being
classified in JOB_META below.

    python scripts/ci_local.py --list
    python scripts/ci_local.py --fast                # lint, test, ui, go-test, helm
    python scripts/ci_local.py --only lint,go-test
    python scripts/ci_local.py --only helm --dry-run # print what would run

Jobs whose tools are missing are reported as SKIP with the reason (use --strict
to treat that as a failure). Needs Python 3.11+ and PyYAML.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "python-ci.yml"
DEFAULT_LOG_DIR = REPO_ROOT / ".ci-local"


@dataclass(frozen=True)
class JobMeta:
    """How a CI job may be run locally (the workflow itself doesn't say)."""

    tools: tuple[str, ...] = ()  # executables that must be on PATH
    files: tuple[str, ...] = ()  # repo-relative paths that must exist
    docker: bool = False  # needs a reachable Docker daemon
    network: bool = False  # needs internet beyond what is already installed
    advisory: bool = False  # failures are warnings, never fail the run
    release_only: bool = False  # CI gates it to release-please PRs
    synth: Optional[str] = None  # job has no `run:` steps; build commands from its matrix


JOB_META: dict[str, JobMeta] = {
    "test": JobMeta(tools=("uv",)),
    "lint": JobMeta(tools=("uv",)),
    "helm": JobMeta(tools=("helm",)),
    "ui": JobMeta(tools=("node", "npm")),
    "docker-build": JobMeta(docker=True, synth="docker_build"),
    "go-test": JobMeta(tools=("go",)),
    "security-audit": JobMeta(tools=("uv", "npm", "go", "pip-audit"), network=True, advisory=True),
    "end-to-end": JobMeta(tools=("uv",), docker=True),
    "ui-browser": JobMeta(tools=("npm",), files=("ui/node_modules/.bin/cypress",), docker=True),
    "acceptance": JobMeta(tools=("uv",), docker=True, release_only=True),
}

# Environment bootstrap that CI needs on a blank runner but that would mutate
# (or slow down) a developer machine. Dropped unless --install is given; run
# `uv sync --dev` / `npm ci` yourself when dependencies change.
_BOOTSTRAP_LINE = re.compile(r"^\s*(?:python3?\s+-m\s+)?pip3?\s+install\b|^\s*npm\s+ci\b|^\s*uv\s+sync\b")
_EXPR = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


class UnsupportedExpression(ValueError):
    """The workflow uses a ${{ }} expression this runner does not understand."""


@dataclass
class Step:
    name: str
    script: str
    env: dict[str, str]
    cwd: Path
    when: str = "success"  # success | failure | always


@dataclass
class Job:
    key: str
    legs: list[dict[str, str]]  # matrix contexts to run (one empty dict if no matrix)
    raw: dict
    meta: JobMeta


@dataclass
class Result:
    job: str
    status: str  # PASS | FAIL | SKIP | WARN
    seconds: float = 0.0
    note: str = ""


# --------------------------------------------------------------------------
# Workflow parsing (pure; unit-tested)
# --------------------------------------------------------------------------

def local_matrix_value(key: str) -> str:
    if key == "python-version":
        return f"{sys.version_info.major}.{sys.version_info.minor}"
    if key == "os":
        return {"linux": "ubuntu-latest", "darwin": "macos-latest", "win32": "windows-latest"}.get(sys.platform, sys.platform)
    raise UnsupportedExpression(f"matrix.{key} has no local value")


def matrix_legs(job: dict) -> list[dict[str, str]]:
    """Contexts to run. An `include`-only matrix runs every entry (e.g. the four
    Docker images); a cross-product (os x python) collapses to one local leg."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not matrix:
        return [{}]
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    if not axes and matrix.get("include"):
        return [{k: str(v) for k, v in entry.items()} for entry in matrix["include"]]
    return [{k: local_matrix_value(k) for k in axes}]


def load_jobs(workflow: Path = DEFAULT_WORKFLOW) -> dict[str, Job]:
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    jobs: dict[str, Job] = {}
    for key, raw in data["jobs"].items():
        if key not in JOB_META:
            raise KeyError(f"CI job {key!r} is not classified in scripts/ci_local.py JOB_META")
        jobs[key] = Job(key=key, legs=matrix_legs(raw), raw=raw, meta=JOB_META[key])
    return jobs


_TMP_PATH = re.compile(r"(?<![\w./-])/tmp/")


def expand_expressions(text: str, context: dict[str, str], runner_temp: str) -> str:
    # CI scripts write scratch files under /tmp; keep them in this run's private
    # temp dir so local runs don't litter the machine or collide with each other.
    text = _TMP_PATH.sub(runner_temp.rstrip("/") + "/", text)

    def replace(match: re.Match) -> str:
        expr = match.group(1)
        if expr == "runner.temp":
            return runner_temp
        if expr.startswith("matrix."):
            name = expr.split(".", 1)[1]
            if name not in context:
                raise UnsupportedExpression(f"${{{{ {expr} }}}} is not available in this matrix leg")
            return context[name]
        raise UnsupportedExpression(f"unsupported expression ${{{{ {expr} }}}}")

    return _EXPR.sub(replace, text)


def drop_bootstrap(script: str) -> tuple[str, list[str]]:
    """Remove install/bootstrap lines (and their backslash continuations)."""
    kept: list[str] = []
    dropped: list[str] = []
    continuing = False
    for line in script.splitlines():
        if continuing or _BOOTSTRAP_LINE.match(line):
            dropped.append(line.strip())
            continuing = line.rstrip().endswith("\\")
        else:
            kept.append(line)
    return "\n".join(kept).strip("\n"), dropped


def _scalar_text(value: object) -> str:
    """`run: true` parses as a YAML boolean but Actions runs it as the string "true"."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _when(step: dict) -> str:
    condition = (step.get("if") or "").strip()
    if not condition:
        return "success"
    if condition in ("always()", "failure()"):
        return condition[:-2]
    raise UnsupportedExpression(f"unsupported step condition {condition!r}")


def plan_steps(
    job: Job,
    leg: dict[str, str],
    runner_temp: str,
    include_bootstrap: bool = False,
    root: Path = REPO_ROOT,
) -> tuple[list[Step], list[str]]:
    """Turn a job's `run:` steps into runnable steps. Returns (steps, notes)."""
    notes: list[str] = []
    default_cwd = ((job.raw.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
    steps: list[Step] = []

    if job.meta.synth == "docker_build":
        if not {"dockerfile", "context", "service"} <= leg.keys():
            raise UnsupportedExpression(f"{job.key}: matrix leg lacks dockerfile/context/service")
        script = f"docker build -f {leg['dockerfile']} {leg['context']} -t hydra-{leg['service']}:ci"
        return [Step(name=f"docker build {leg['service']}", script=script, env={}, cwd=root)], notes

    for raw in job.raw.get("steps", []):
        script = raw.get("run")
        if script is None:
            continue  # `uses:` steps (checkout, setup-*, caches) are not reproduced locally
        script = _scalar_text(script)
        name = raw.get("name") or script.splitlines()[0][:60]
        script = expand_expressions(script, leg, runner_temp)
        if not include_bootstrap:
            script, dropped = drop_bootstrap(script)
            if dropped:
                notes.append(f"{name}: skipped bootstrap ({'; '.join(dropped)})")
            if not script.strip():
                continue
        env = {k: expand_expressions(str(v), leg, runner_temp) for k, v in (raw.get("env") or {}).items()}
        cwd = root / raw.get("working-directory", default_cwd)
        steps.append(Step(name=name, script=script, env=env, cwd=cwd, when=_when(raw)))
    return steps, notes


# --------------------------------------------------------------------------
# Selection and requirements (pure given injected probes; unit-tested)
# --------------------------------------------------------------------------

def select_jobs(
    jobs: dict[str, Job],
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
    fast: bool = False,
    skip_docker: bool = False,
    release: bool = False,
    audit: bool = False,
) -> tuple[list[Job], list[Result]]:
    """Choose jobs to run; everything else becomes a SKIP result with a reason."""
    only, skip = list(only), set(skip)
    unknown = [name for name in [*only, *skip] if name not in jobs]
    if unknown:
        raise KeyError(f"unknown job(s): {', '.join(unknown)} (known: {', '.join(jobs)})")
    selected: list[Job] = []
    skipped: list[Result] = []
    for key, job in jobs.items():
        meta = job.meta
        reason = None
        if only and key not in only:
            continue  # not requested: not even reported
        if key in skip:
            reason = "excluded with --skip"
        elif meta.release_only and not release and key not in only:
            reason = "release-please PRs only (use --release)"
        elif meta.docker and (fast or skip_docker):
            reason = "needs Docker (skipped by --fast/--skip-docker)"
        elif meta.network and fast and not audit:
            reason = "needs network (skipped by --fast)"
        if reason:
            skipped.append(Result(key, "SKIP", note=reason))
        else:
            selected.append(job)
    return selected, skipped


def missing_requirement(
    meta: JobMeta,
    root: Path = REPO_ROOT,
    which: Callable[[str], Optional[str]] = shutil.which,
    docker_ok: Callable[[], bool] = lambda: docker_daemon_reachable(),
) -> Optional[str]:
    for tool in meta.tools:
        if not which(tool):
            return f"{tool} not found on PATH"
    for rel in meta.files:
        if not (root / rel).exists():
            return f"{rel} not found (run the install step, e.g. `npm ci`)"
    if meta.docker:
        if not which("docker"):
            return "docker not found on PATH"
        if not docker_ok():
            return "docker daemon unreachable"
    return None


_docker_state: Optional[bool] = None


def docker_daemon_reachable() -> bool:
    global _docker_state
    if _docker_state is None:
        try:
            _docker_state = subprocess.run(
                ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _docker_state = False
    return _docker_state


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def step_env(step: Step, runner_temp: str, root: Path = REPO_ROOT) -> dict[str, str]:
    env = dict(os.environ)
    venv_bin = root / ".venv" / "bin"
    if venv_bin.is_dir():  # so inline `python3 -c "import yaml"` steps find project deps
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    env.update({"CI": "true", "RUNNER_TEMP": runner_temp})
    env.update(step.env)
    return env


def run_script(step: Step, runner_temp: str, log, echo: bool) -> int:
    proc = subprocess.Popen(
        ["bash", "-e", "-c", step.script],
        cwd=step.cwd,
        env=step_env(step, runner_temp),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if echo:
                sys.stdout.write(line)
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        raise


def run_job(job: Job, args: argparse.Namespace, runner_temp: str, log_dir: Path) -> Result:
    started = time.monotonic()
    failed_note = ""
    ok = True
    for leg in job.legs:
        label = job.key + (f"[{leg.get('service') or ','.join(leg.values())}]" if leg and job.meta.synth else "")
        steps, notes = plan_steps(job, leg, runner_temp, include_bootstrap=args.install)
        log_path = log_dir / f"{label.replace('/', '_')}.log"
        print(f"\n=== {label} ===", flush=True)
        for note in notes:
            print(f"  (note) {note}")
        if args.dry_run:
            for step in steps:
                print(f"  [{step.when}] {step.name} (cwd={step.cwd.relative_to(REPO_ROOT) if step.cwd != REPO_ROOT else '.'})")
                for line in step.script.splitlines():
                    print(f"      {line}")
            continue
        leg_ok = True
        with log_path.open("w", encoding="utf-8") as log:
            for step in steps:
                if step.when == "success" and not leg_ok:
                    continue
                if step.when == "failure" and leg_ok:
                    continue
                print(f"--- {step.name}", flush=True)
                log.write(f"\n--- {step.name}\n")
                code = run_script(step, runner_temp, log, echo=not args.quiet)
                if code != 0 and step.when == "success":
                    leg_ok = False
                    ok = False
                    failed_note = f"{label}: step '{step.name}' exited {code} (log: {log_path})"
        print(f"=== {label}: {'PASS' if leg_ok else 'FAIL'} ===", flush=True)
    status = "PASS" if ok else ("WARN" if job.meta.advisory else "FAIL")
    if args.dry_run:
        status, failed_note = "PASS", "dry run"
    return Result(job.key, status, time.monotonic() - started, failed_note)


def print_summary(results: list[Result]) -> None:
    print("\n" + "=" * 72)
    print(f"{'JOB':<18}{'RESULT':<8}{'TIME':>8}  NOTE")
    for r in results:
        print(f"{r.job:<18}{r.status:<8}{r.seconds:>7.1f}s  {r.note}")
    print("=" * 72)


def exit_code(results: list[Result], strict: bool) -> int:
    for r in results:
        if r.status == "FAIL" or (strict and r.status == "SKIP" and "excluded" not in r.note and "--release" not in r.note):
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the repo's GitHub Actions CI jobs locally.")
    p.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW, help="workflow file (default: python-ci.yml)")
    p.add_argument("--list", action="store_true", help="list jobs and what they need, then exit")
    p.add_argument("--only", default="", help="comma-separated jobs to run")
    p.add_argument("--skip", default="", help="comma-separated jobs to skip")
    p.add_argument("--fast", action="store_true", help="skip jobs needing Docker or network")
    p.add_argument("--skip-docker", action="store_true", help="skip jobs needing Docker")
    p.add_argument("--release", action="store_true", help="include release-PR-only jobs (acceptance)")
    p.add_argument("--audit", action="store_true", help="with --fast, still run the advisory security-audit")
    p.add_argument("--install", action="store_true", help="also run bootstrap lines (pip install, npm ci, uv sync)")
    p.add_argument("--strict", action="store_true", help="a job skipped for a missing tool counts as a failure")
    p.add_argument("--fail-fast", action="store_true", help="stop after the first failed job")
    p.add_argument("--dry-run", action="store_true", help="print the commands that would run")
    p.add_argument("-q", "--quiet", action="store_true", help="write job output only to the log files")
    p.add_argument("--logs", type=Path, default=DEFAULT_LOG_DIR, help="directory for per-job logs")
    return p


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def describe(job: Job) -> str:
    m = job.meta
    flag_values = (("docker", m.docker), ("network", m.network), ("advisory", m.advisory), ("release-only", m.release_only))
    flags = [name for name, on in flag_values if on]
    needs = ", ".join(m.tools + m.files) or "-"
    return f"{job.key:<16} needs: {needs:<44} {' '.join(f'[{f}]' for f in flags)}"


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        jobs = load_jobs(args.workflow)
        if args.list:
            for job in jobs.values():
                print(describe(job))
            return 0
        selected, results = select_jobs(
            jobs, _csv(args.only), _csv(args.skip), args.fast, args.skip_docker, args.release, args.audit
        )
    except (KeyError, UnsupportedExpression, FileNotFoundError) as exc:
        print(f"ci_local: {exc}", file=sys.stderr)
        return 2

    args.logs.mkdir(parents=True, exist_ok=True)
    runner_temp = tempfile.mkdtemp(prefix="ci-local-")
    try:
        for job in selected:
            reason = None if args.dry_run else missing_requirement(job.meta)
            if reason:
                results.append(Result(job.key, "SKIP", note=reason))
                continue
            try:
                results.append(run_job(job, args, runner_temp, args.logs))
            except UnsupportedExpression as exc:
                print(f"ci_local: {job.key}: {exc}", file=sys.stderr)
                results.append(Result(job.key, "FAIL", note=str(exc)))
            if args.fail_fast and results[-1].status == "FAIL":
                break
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        shutil.rmtree(runner_temp, ignore_errors=True)

    order = {key: i for i, key in enumerate(jobs)}
    results.sort(key=lambda r: order.get(r.job, 99))
    print_summary(results)
    return exit_code(results, args.strict)


if __name__ == "__main__":
    sys.exit(main())
