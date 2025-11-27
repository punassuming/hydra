# Testing guardrails

## One-shot test runner
- `./scripts/test-all.sh` runs scheduler/worker unit tests and, if `E2E=1`, the end-to-end test (requires the full stack running). It also runs `npm run build` in `ui/` when `node_modules` exists.
- Customize pytest args with `PYTEST_ARGS="--maxfail=1 -q" ./scripts/test-all.sh`.
- Skip UI build if you haven't installed deps yet; once ready, `cd ui && npm install` to enable the check.

## Git hook to enforce tests before push
- Opt-in once: `git config core.hooksPath .githooks`
- The `.githooks/pre-push` hook calls `scripts/test-all.sh` and blocks pushes on failures. Set `SKIP_TESTS=1 git push` to bypass when you must.

## Recommendations
- Run with `E2E=1` before merging to catch regressions when the full stack is up.
- Keep `node_modules` around for UI builds to avoid repeated installs; otherwise the UI check is skipped.
