"""Tests for scripts/ci_local.py, the local GitHub Actions job runner."""

import argparse
import importlib.util
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ci_local", ROOT / "scripts" / "ci_local.py")
ci = importlib.util.module_from_spec(_spec)
sys.modules["ci_local"] = ci
_spec.loader.exec_module(ci)

needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs steps through bash")


@pytest.fixture(scope="module")
def jobs():
    return ci.load_jobs()


# ---- parsing the real workflow ---------------------------------------------------------

def test_every_ci_job_is_classified(jobs):
    # load_jobs raises KeyError for an unclassified job; also no stale entries.
    assert set(jobs) == set(ci.JOB_META)


def test_docker_build_expands_one_leg_per_image(jobs):
    services = [leg["service"] for leg in jobs["docker-build"].legs]
    assert services == ["scheduler", "worker", "ui", "go-worker"]


def test_cross_product_matrix_collapses_to_one_local_leg(jobs):
    assert len(jobs["test"].legs) == 1
    assert jobs["test"].legs[0]["python-version"].count(".") == 1


def test_test_job_drops_bootstrap_and_expands_runner_temp(jobs):
    steps, notes = ci.plan_steps(jobs["test"], jobs["test"].legs[0], "/tmp/rt")
    assert [s.name for s in steps] == ["Run tests"]
    assert "--basetemp=\"/tmp/rt/pytest\"" in steps[0].script
    assert "uv sync" not in steps[0].script and any("skipped bootstrap" in n for n in notes)


def test_install_flag_keeps_bootstrap_lines(jobs):
    steps, _ = ci.plan_steps(jobs["test"], jobs["test"].legs[0], "/tmp/rt", include_bootstrap=True)
    assert "uv sync --frozen --dev" in steps[0].script or any("uv sync" in s.script for s in steps)


def test_default_and_step_working_directories(jobs):
    ui_steps, _ = ci.plan_steps(jobs["ui"], {}, "/tmp/rt")
    assert {s.cwd.name for s in ui_steps} == {"ui"}
    browser, _ = ci.plan_steps(jobs["ui-browser"], {}, "/tmp/rt")
    by_name = {s.name: s.cwd for s in browser}
    assert by_name["Start browser test stack"] == ci.REPO_ROOT  # step `working-directory: .` overrides the ui default
    assert by_name["Run authenticated operator journey"].name == "ui"


def test_cleanup_steps_keep_their_conditions(jobs):
    steps, _ = ci.plan_steps(jobs["end-to-end"], {}, "/tmp/rt")
    whens = {s.name: s.when for s in steps}
    assert whens["Show service logs after failure"] == "failure"
    assert whens["Stop test stack"] == "always"
    assert whens["Run full-stack smoke test"] == "success"


def test_docker_build_commands_come_from_the_matrix(jobs):
    job = jobs["docker-build"]
    commands = [ci.plan_steps(job, leg, "/tmp/rt")[0][0].script for leg in job.legs]
    assert "docker build -f ui/Dockerfile ui -t hydra-ui:ci" in commands
    assert "docker build -f scheduler/Dockerfile . -t hydra-scheduler:ci" in commands


# ---- expressions and bootstrap filtering -----------------------------------------------

def test_expand_expressions():
    assert ci.expand_expressions("x ${{ runner.temp }}/y", {}, "/tmp/rt") == "x /tmp/rt/y"
    assert ci.expand_expressions("${{ matrix.service }}", {"service": "ui"}, "/tmp/rt") == "ui"


def test_tmp_paths_are_remapped_into_the_private_temp_dir():
    out = ci.expand_expressions("cat > /tmp/v.yaml; helm -f /tmp/v.yaml; ls /var/tmp/x", {}, "/tmp/rt")
    assert out == "cat > /tmp/rt/v.yaml; helm -f /tmp/rt/v.yaml; ls /var/tmp/x"


def test_windows_style_temp_dir_is_safe_in_expansion():
    """Regression: a Windows temp path used as a re.sub replacement raised
    `bad escape \\U`, and its backslashes would be eaten as escapes by bash."""
    win = "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\ci-local-x"
    assert ci.expand_expressions("cat > /tmp/v.yaml", {}, win) == "cat > C:/Users/RUNNER~1/AppData/Local/Temp/ci-local-x/v.yaml"
    assert ci.expand_expressions("--basetemp=${{ runner.temp }}/pytest", {}, win) == (
        "--basetemp=C:/Users/RUNNER~1/AppData/Local/Temp/ci-local-x/pytest"
    )
    assert ci.expand_expressions("cat > /tmp/v.yaml", {}, "/tmp/rt/") == "cat > /tmp/rt/v.yaml"


@pytest.mark.parametrize("expr", ["secrets.TOKEN", "github.head_ref", "matrix.missing", "env.X"])
def test_unsupported_expressions_fail_loudly(expr):
    with pytest.raises(ci.UnsupportedExpression):
        ci.expand_expressions("${{ %s }}" % expr, {}, "/tmp/rt")


def test_scalar_run_values_are_run_as_strings():
    assert ci._scalar_text(True) == "true"
    assert ci._scalar_text(False) == "false"
    assert ci._scalar_text(1) == "1"
    assert ci._scalar_text("echo hi") == "echo hi"


def test_unsupported_step_condition_is_rejected():
    with pytest.raises(ci.UnsupportedExpression):
        ci._when({"if": "github.event_name == 'push'"})


def test_drop_bootstrap_handles_continuations_and_keeps_real_commands():
    script = textwrap.dedent(
        """\
        python -m pip install uv==0.5.13 \\
            pip-audit
        uv export -o out.txt
        npm ci
        pip-audit -r out.txt
        """
    )
    kept, dropped = ci.drop_bootstrap(script)
    assert kept.splitlines() == ["uv export -o out.txt", "pip-audit -r out.txt"]
    assert len(dropped) == 3


# ---- selection and requirements --------------------------------------------------------

def names(selected):
    return [j.key for j in selected]


def test_default_selection_excludes_only_release_jobs(jobs):
    selected, skipped = ci.select_jobs(jobs)
    assert "acceptance" not in names(selected)
    assert any(r.job == "acceptance" and "--release" in r.note for r in skipped)


def test_release_flag_includes_acceptance(jobs):
    selected, _ = ci.select_jobs(jobs, release=True)
    assert "acceptance" in names(selected)


def test_fast_skips_docker_and_network_jobs(jobs):
    selected, skipped = ci.select_jobs(jobs, fast=True)
    assert names(selected) == ["test", "lint", "helm", "ui", "go-test"]
    assert {r.job for r in skipped} >= {"docker-build", "end-to-end", "ui-browser", "security-audit"}


def test_audit_flag_keeps_security_audit_under_fast(jobs):
    selected, _ = ci.select_jobs(jobs, fast=True, audit=True)
    assert "security-audit" in names(selected)


def test_only_and_skip(jobs):
    selected, skipped = ci.select_jobs(jobs, only=["lint", "go-test"], skip=["go-test"])
    assert names(selected) == ["lint"]
    assert [r.job for r in skipped] == ["go-test"]


def test_unknown_job_name_is_an_error(jobs):
    with pytest.raises(KeyError):
        ci.select_jobs(jobs, only=["nope"])


def test_missing_requirement_reports_the_first_gap():
    meta = ci.JobMeta(tools=("a", "b"), files=("x/y",), docker=True)
    root = Path("/nonexistent-root")
    assert ci.missing_requirement(meta, root, which=lambda t: None) == "a not found on PATH"
    assert ci.missing_requirement(meta, root, which=lambda t: "/bin/" + t).startswith("x/y not found")
    nofiles = ci.JobMeta(docker=True)
    assert ci.missing_requirement(nofiles, root, which=lambda t: None) == "docker not found on PATH"
    docker_on_path = {"which": lambda t: "/bin/docker"}
    assert ci.missing_requirement(nofiles, root, **docker_on_path, docker_ok=lambda: False) == "docker daemon unreachable"
    assert ci.missing_requirement(nofiles, root, **docker_on_path, docker_ok=lambda: True) is None


def test_exit_code_rules():
    R = ci.Result
    assert ci.exit_code([R("a", "PASS"), R("b", "WARN")], strict=False) == 0
    assert ci.exit_code([R("a", "FAIL")], strict=False) == 1
    assert ci.exit_code([R("a", "SKIP", note="helm not found on PATH")], strict=False) == 0
    assert ci.exit_code([R("a", "SKIP", note="helm not found on PATH")], strict=True) == 1
    assert ci.exit_code([R("a", "SKIP", note="release-please PRs only (use --release)")], strict=True) == 0


def test_list_and_unknown_job_cli(capsys):
    assert ci.main(["--list"]) == 0
    assert "docker-build" in capsys.readouterr().out
    assert ci.main(["--only", "nope"]) == 2


# ---- executing steps --------------------------------------------------------------------

def _run(tmp_path, monkeypatch, steps_yaml, job="lint", meta=None, extra=()):
    # Steps reference $MARK; a literal /tmp path would be remapped into the runner's temp dir.
    monkeypatch.setenv("MARK", str(tmp_path))
    wf = tmp_path / "wf.yml"
    body = textwrap.indent(textwrap.dedent(steps_yaml), "      ")
    wf.write_text(f"jobs:\n  {job}:\n    runs-on: ubuntu-latest\n    steps:\n{body}")
    # Every other job is irrelevant here; classify only what this workflow defines.
    monkeypatch.setattr(ci, "JOB_META", {job: meta or ci.JobMeta()})
    return ci.main(["--workflow", str(wf), "--logs", str(tmp_path / "logs"), "-q", *extra])


@needs_bash
def test_passing_job_exits_zero(tmp_path, monkeypatch, capsys):
    code = _run(tmp_path, monkeypatch, "- run: echo hello\n")
    assert code == 0
    assert "PASS" in capsys.readouterr().out
    assert "hello" in (tmp_path / "logs" / "lint.log").read_text()


@needs_bash
def test_failing_step_fails_job_and_skips_later_steps_but_runs_cleanup(tmp_path, monkeypatch):
    steps = """\
    - name: boom
      run: exit 3
    - name: never
      run: touch $MARK/should-not-exist
    - name: failure-hook
      if: failure()
      run: touch $MARK/failure-ran
    - name: cleanup
      if: always()
      run: touch $MARK/cleaned
    """
    assert _run(tmp_path, monkeypatch, steps) == 1
    assert (tmp_path / "cleaned").exists()
    assert (tmp_path / "failure-ran").exists()
    assert not (tmp_path / "should-not-exist").exists()


@needs_bash
def test_failure_hook_does_not_run_when_job_passes(tmp_path, monkeypatch):
    steps = """\
    - run: true
    - if: failure()
      run: touch $MARK/failure-ran
    - if: always()
      run: touch $MARK/always-ran
    """
    assert _run(tmp_path, monkeypatch, steps) == 0
    assert not (tmp_path / "failure-ran").exists()
    assert (tmp_path / "always-ran").exists()


@needs_bash
def test_advisory_failure_is_a_warning_not_a_failure(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, "- run: exit 1\n", meta=ci.JobMeta(advisory=True)) == 0
    assert "WARN" in capsys.readouterr().out


@needs_bash
def test_bootstrap_lines_are_not_executed_by_default(tmp_path, monkeypatch):
    steps = """\
    - run: |
        npm ci
        touch $MARK/ran-real-command
    """
    assert _run(tmp_path, monkeypatch, steps) == 0  # `npm ci` would fail/hang if executed
    assert (tmp_path / "ran-real-command").exists()


def test_missing_tool_skips_unless_strict(tmp_path, monkeypatch, capsys):
    meta = ci.JobMeta(tools=("definitely-not-a-real-tool-xyz",))
    assert _run(tmp_path, monkeypatch, "- run: true\n", meta=meta) == 0
    assert "definitely-not-a-real-tool-xyz not found" in capsys.readouterr().out
    assert _run(tmp_path, monkeypatch, "- run: true\n", meta=meta, extra=("--strict",)) == 1


def test_dry_run_prints_without_executing(tmp_path, monkeypatch, capsys):
    steps = "- run: touch $MARK/executed\n"
    assert _run(tmp_path, monkeypatch, steps, extra=("--dry-run",)) == 0
    assert not (tmp_path / "executed").exists()
    assert "touch" in capsys.readouterr().out


def test_namespace_helper_unused_arg_shape():
    # build_parser must expose every flag run_job reads.
    ns = ci.build_parser().parse_args([])
    assert isinstance(ns, argparse.Namespace)
    assert {"install", "dry_run", "quiet"} <= set(vars(ns))
