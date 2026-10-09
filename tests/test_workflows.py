"""Static checks on the GitHub Actions workflows (nothing is executed).

These catch CI config drift that would otherwise only show up as a red or,
worse, silently-skipped check on a real run: dangling script paths, floating
action refs, a job added without being classified for scripts/ci_local.py,
container names that no longer match their compose project, etc.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
CI_WORKFLOW = WORKFLOW_DIR / "python-ci.yml"

_spec = importlib.util.spec_from_file_location("ci_local", ROOT / "scripts" / "ci_local.py")
ci_local = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("ci_local", ci_local)
_spec.loader.exec_module(ci_local)


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_steps(data: dict):
    """Yield (job_key, step, working_dir) for every `run:` step."""
    for key, job in data["jobs"].items():
        default_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for step in job.get("steps", []):
            if "run" in step:
                yield key, step, ROOT / step.get("working-directory", default_wd)


ids = [p.name for p in WORKFLOWS]


def test_workflows_exist():
    assert CI_WORKFLOW in WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=ids)
def test_workflow_is_well_formed(path):
    data = load(path)
    assert data.get("name"), "workflow needs a name"
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    assert data.get("on") or data.get(True), "workflow has no trigger"
    assert data.get("jobs")
    for key, job in data["jobs"].items():
        assert "runs-on" in job or "uses" in job, f"{key}: no runs-on"
        assert job.get("steps") or "uses" in job, f"{key}: no steps"


@pytest.mark.parametrize("path", WORKFLOWS, ids=ids)
def test_actions_are_pinned_to_a_version(path):
    pinned = re.compile(r"^[\w.-]+/[\w./-]+@(v\d+(\.\d+)*|[0-9a-f]{40})$")
    for key, job in load(path)["jobs"].items():
        for step in job.get("steps", []):
            ref = step.get("uses")
            if ref and not ref.startswith("./"):
                assert pinned.match(ref), f"{path.name}:{key}: '{ref}' is not pinned to a version tag or commit"


@pytest.mark.parametrize("path", WORKFLOWS, ids=ids)
def test_every_job_declares_permissions_and_only_known_writers_write(path):
    data = load(path)
    write_allowed = {"push-images.yml", "release-please.yml"}
    for key, job in data["jobs"].items():
        perms = job.get("permissions") if "permissions" in job else data.get("permissions")
        assert perms is not None, f"{path.name}:{key}: no explicit permissions (defaults to broad token access)"
        if path.name not in write_allowed:
            assert "write" not in set(perms.values()), f"{path.name}:{key}: unexpected write permission"


@pytest.mark.parametrize("path", WORKFLOWS, ids=ids)
def test_repo_paths_referenced_by_run_steps_exist(path):
    top_levels = r"(?:deploy|tests|scripts|\.github|ui|go-worker|scheduler|worker|cli|docs)"
    file_token = re.compile(r"(?<![\w/.$-])((?:[\w.-]+/)*[\w-]+\.(?:ya?ml|py|sh|ts|tsx|json|toml|cjs))\b")
    dir_token = re.compile(rf"(?<![\w/.$-])({top_levels}/[\w./-]*)")
    for key, step, cwd in run_steps(load(path)):
        script = step["run"]
        for match in [*file_token.findall(script), *dir_token.findall(script)]:
            token = match.rstrip("/.")
            if not token or "$" in token or "*" in token:
                continue
            assert (cwd / token).exists() or (ROOT / token).exists(), (
                f"{path.name}:{key} step '{step.get('name')}': '{token}' does not exist (cwd={cwd.relative_to(ROOT)})"
            )


def test_every_ci_job_is_classified_for_the_local_runner():
    jobs = set(load(CI_WORKFLOW)["jobs"])
    assert jobs == set(ci_local.JOB_META), (
        f"update JOB_META in scripts/ci_local.py: missing={jobs - set(ci_local.JOB_META)}, "
        f"stale={set(ci_local.JOB_META) - jobs}"
    )


def test_local_runner_can_plan_every_ci_job():
    """No job uses an expression/condition the runner can't translate."""
    for job in ci_local.load_jobs(CI_WORKFLOW).values():
        for leg in job.legs:
            ci_local.plan_steps(job, leg, "/tmp/rt")


def test_uv_version_is_pinned_consistently():
    versions = set()
    for path in WORKFLOWS:
        for _key, step, _cwd in run_steps(load(path)):
            versions.update(re.findall(r"uv==([\d.]+)", step["run"]))
    assert len(versions) == 1, f"inconsistent uv pins: {sorted(versions)}"


def test_docker_build_matrix_points_at_real_files():
    include = load(CI_WORKFLOW)["jobs"]["docker-build"]["strategy"]["matrix"]["include"]
    assert include
    for entry in include:
        assert (ROOT / entry["dockerfile"]).is_file(), entry
        assert (ROOT / entry["context"]).is_dir(), entry


def test_e2e_overlay_defines_the_worker_and_compose_services_exist():
    base = load(ROOT / "docker-compose.yml")
    overlay = load(ROOT / ".github" / "compose.e2e.yml")
    assert "worker" in overlay["services"]
    known = set(base["services"]) | set(overlay["services"])
    for _key, step, _cwd in run_steps(load(CI_WORKFLOW)):
        for line in re.findall(r"docker compose[^\n]*?\bup\b[^\n]*", step["run"]):
            services = [t for t in line.split() if re.fullmatch(r"[a-z][a-z0-9-]*", t)]
            names = services[services.index("up") + 1:] if "up" in services else []
            for name in (n for n in names if n not in ("d", "build")):
                assert name in known, f"compose service '{name}' not defined: {line}"


def test_acceptance_job_container_names_match_its_compose_project():
    """The acceptance suite restarts Redis/Mongo by container name; if these
    drift from `-p <project>` the resilience tests silently skip instead of
    running (a real bug fixed in review of the slice-1 PR)."""
    job = load(CI_WORKFLOW)["jobs"]["acceptance"]
    start = next(s for s in job["steps"] if "compose" in s.get("run", "") and " up " in s["run"])
    project = re.search(r"-p\s+(\S+)", start["run"]).group(1)
    env = next(s for s in job["steps"] if s.get("name") == "Run acceptance suite")["env"]
    assert env["ACCEPTANCE_DOCKER_NETWORK"] == f"{project}_backend"
    assert env["ACCEPTANCE_DOCKER_REDIS_CONTAINER"] == f"{project}-redis-1"
    assert env["ACCEPTANCE_DOCKER_MONGO_CONTAINER"] == f"{project}-mongo-1"
    compose = load(ROOT / "docker-compose.yml")
    assert {"redis", "mongo"} <= set(compose["services"]) and "backend" in compose["networks"]


def test_acceptance_job_is_gated_to_release_prs():
    condition = load(CI_WORKFLOW)["jobs"]["acceptance"]["if"]
    assert "release-please--" in condition


def test_commitlint_types_match_release_please_sections():
    """A type commitlint accepts but release-please ignores (or vice versa) would
    pass CI yet be invisible to versioning/changelog."""
    text = (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
    block = re.search(r'"type-enum"\s*:\s*\[\s*\d+\s*,\s*"always"\s*,\s*\[(.*?)\]', text, re.S).group(1)
    lint_types = set(re.findall(r'"([a-z]+)"', block))
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    release_types = {section["type"] for section in config["changelog-sections"]}
    assert lint_types == release_types


# ---- Dependabot config ------------------------------------------------------------------

DEPENDABOT = ROOT / ".github" / "dependabot.yml"


def test_dependabot_python_updates_use_uv_so_the_lock_is_updated():
    """CI installs with `uv sync --frozen`; a `pip` ecosystem would edit only
    pyproject.toml, so its PRs would test the old locked versions."""
    ecosystems = {u["package-ecosystem"] for u in load(DEPENDABOT)["updates"]}
    assert (ROOT / "uv.lock").exists()
    assert "uv" in ecosystems
    assert "pip" not in ecosystems


def test_dependabot_directories_exist():
    for update in load(DEPENDABOT)["updates"]:
        assert (ROOT / update["directory"].lstrip("/")).is_dir(), update


def test_dependabot_covers_every_dockerfile():
    covered = {u["directory"] for u in load(DEPENDABOT)["updates"] if u["package-ecosystem"] == "docker"}
    dockerfiles = {"/" + p.parent.name for p in ROOT.glob("*/Dockerfile")}
    assert dockerfiles <= covered, f"Dockerfiles not watched by Dependabot: {sorted(dockerfiles - covered)}"


def test_commitlint_does_not_cap_body_or_footer_line_length():
    """Dependabot pastes long lines into commit bodies; capping them failed good PRs."""
    text = (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
    assert re.search(r'"body-max-line-length"\s*:\s*\[\s*0\s*\]', text)
    assert re.search(r'"footer-max-line-length"\s*:\s*\[\s*0\s*\]', text)
