# Testing guardrails

Install the locked Python environment with `uv sync --dev`. `pyproject.toml`
and `uv.lock` are the dependency source of truth for local development, CI,
and the Python container images.

## Reproduce CI locally: `scripts/ci_local.py`
CI runs on GitHub, but you can run the same jobs before pushing. The runner *parses* `.github/workflows/python-ci.yml` and executes each job's `run:` steps, so it cannot drift from the workflow.

```bash
python scripts/ci_local.py --list                 # jobs, and what each needs
python scripts/ci_local.py --fast                 # no Docker/network: test, lint, helm, ui, go-test
python scripts/ci_local.py --only lint,go-test    # specific jobs
python scripts/ci_local.py --skip-docker          # everything except Docker jobs
python scripts/ci_local.py --release              # also the release-PR-only acceptance job
python scripts/ci_local.py --only helm --dry-run  # print the commands without running them
```

- It needs Python 3.11+ and PyYAML (`uv run python scripts/ci_local.py ...` has both).
- A job whose tools are missing (no `helm`, no reachable Docker daemon, ...) is reported as `SKIP` with the reason; add `--strict` to treat that as a failure. Exit code is non-zero if any job fails. The advisory `security-audit` job only warns.
- Output of each job is saved under `.ci-local/` (git-ignored); `-q` hides command output on the terminal (job and step headers and the summary table still print).
- It does **not** reproduce `uses:` steps (checkout, `setup-*`, caches, buildx), the other-OS legs of the Python matrix, or the publish/release workflows. It assumes your toolchains are installed, so install lines (`pip install`, `npm ci`, `uv sync`) are skipped unless you pass `--install`; run `uv sync --dev` and `cd ui && npm ci` yourself when dependencies change. `/tmp` paths used by CI scripts are mapped to a private temp directory.
- Jobs are classified in `JOB_META` at the top of the script. `tests/test_workflows.py` fails if a CI job is added without being classified there.

### Workflow checks without running anything
`tests/test_workflows.py` validates the workflow files statically (they run in the normal `pytest` job): actions pinned to a version, explicit least-privilege permissions, referenced scripts/paths exist, one consistent `uv` pin, the acceptance job's container names match its compose project, and commitlint's types match release-please's changelog sections.

## Quick test runner
- `./scripts/test-all.sh` is a **subset**: it runs only `tests/test_scheduler.py` and `tests/test_worker.py` (plus the end-to-end test if `E2E=1`, which needs the full stack) and `npm run build` in `ui/` when `node_modules` exists. It does not run ruff, the Go checks, vitest or helm; use `ci_local.py` for those.
- Customize pytest args with `PYTEST_ARGS="--maxfail=1 -q" ./scripts/test-all.sh`.
- Skip UI build if you haven't installed deps yet; once ready, `cd ui && npm install` to enable the check.

## Git hook to enforce tests before push
- Opt-in once: `git config core.hooksPath .githooks`
- The `.githooks/pre-push` hook calls `scripts/test-all.sh` and blocks pushes on failures. Set `SKIP_TESTS=1 git push` to bypass when you must.

## Recommendations
- Start the smoke-test stack with `docker compose -f docker-compose.yml -f .github/compose.e2e.yml up -d --build redis mongo scheduler worker`, then run `HYDRA_E2E=1 uv run pytest tests/test_end_to_end.py`.
- Keep `node_modules` around for UI builds to avoid repeated installs; otherwise the UI check is skipped.
