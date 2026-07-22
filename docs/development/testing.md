# Testing guardrails

Install the locked Python environment with `uv sync --dev`. `pyproject.toml`
and `uv.lock` are the dependency source of truth for local development, CI,
and the Python container images.

## One-shot test runner
- `./scripts/test-all.sh` runs scheduler/worker unit tests and, if `E2E=1`, the end-to-end test (requires the full stack running). It also runs `npm run build` in `ui/` when `node_modules` exists.
- Customize pytest args with `PYTEST_ARGS="--maxfail=1 -q" ./scripts/test-all.sh`.
- Skip UI build if you haven't installed deps yet; once ready, `cd ui && npm install` to enable the check.

## Git hook to enforce tests before push
- Opt-in once: `git config core.hooksPath .githooks`
- The `.githooks/pre-push` hook calls `scripts/test-all.sh` and blocks pushes on failures. Set `SKIP_TESTS=1 git push` to bypass when you must.

## Recommendations
- Start the smoke-test stack with `docker compose -f docker-compose.yml -f .github/compose.e2e.yml up -d --build redis mongo scheduler worker`, then run `HYDRA_E2E=1 uv run pytest tests/test_end_to_end.py`.
- Keep `node_modules` around for UI builds to avoid repeated installs; otherwise the UI check is skipped.
