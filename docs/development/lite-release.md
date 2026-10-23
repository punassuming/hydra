# Releasing the lite edition (merging `feat/hydra-lite` to `main`)

Hydra lite ships **with the main version**: one product, two editions, one `release-please` package, one version and
changelog. It adds no container image. Users get it from the release's wheel (`uv tool install hydra-jobs --from
<wheel URL>`, see `docs/lite/install.md`). Because both editions share the job/run/worker shapes and several modules
(`scheduler/utils/*`, `ScheduleConfig`), a breaking change to that contract is a breaking change for both.

## How a release is produced

1. Merging a PR to `main` runs `release-please.yml`, which opens or updates the standing release PR (version bump,
   `CHANGELOG.md`, Helm chart version).
2. Merging that PR makes release-please create the tag `vX.Y.Z` (no component prefix: `include-component-in-tag` is
   `false`, otherwise the tag is `hydra-vX.Y.Z` and `push-images.yml`'s `v*` filter never matches) and the GitHub Release.
3. In the same run, `release-please.yml` **calls** `push-images.yml` (the four images to GHCR) and `release-wheel.yml`
   (sdist + wheel attached to the Release). They are called rather than left to tag events because anything created
   with the default `GITHUB_TOKEN` does not trigger other workflows. If the repository has a PAT/GitHub App token in
   the `RELEASE_PLEASE_TOKEN` secret, the tag push also triggers `push-images.yml`; its `concurrency` group keeps the
   two runs from racing and the immutable image tag is idempotent.

The release PR itself gets no CI with the default token (same limitation); that is why the merge checklist below is
run on the feature PR.

## Merge checklist

- [ ] Open the PR from `feat/hydra-lite` to `main`; **all** jobs are green, including Windows/macOS legs, the
  `docker-build` jobs (they exercise `--extra full`), the Windows Task Scheduler round-trip test, and the lean-import
  guard (`tests/lite/test_lean_imports.py`).
- [ ] Run locally and record the numbers in the PR: `uv run pytest tests`, `python scripts/ci_local.py --fast`,
  `HYDRA_STRESS=1 uv run pytest tests/lite/test_stress_smoke.py`, and optionally
  `uv run python scripts/lite_stress.py --profile full` against `docs/lite/stress-testing.md`.
- [ ] On a clean venv: `uv run python scripts/lite_install_smoke.py` (lean install, no extras, runs a job, serves the
  status page).
- [ ] Manual Windows pass (the sandbox could not do this): `hydra-ctl lite service install`, log off and on, kill
  `pythonw.exe` and confirm Task Scheduler restarts it, `service install` again to upgrade in place, `service remove`.
- [ ] Commit hygiene: every commit is Conventional (the repo merges with a merge commit, so each one is scanned).
  At the time of writing the branch has 20 commits: `feat(lite)` x8, `feat(cli)` x2, `fix(scheduler)` x2,
  `fix(lite)`, `refactor*` x4, `test(lite)` x2, `docs(lite)`, `build`. Expect **one minor bump** (pre-1.0:
  `bump-minor-pre-major`), and `docs`/`test`/`refactor`/`build` do not appear in the changelog.
- [ ] Say in the PR description (release-please takes the changelog from commit subjects, so also add it to the
  release PR's notes before merging it) that the following change **full-edition behaviour or tooling**:
  - cron schedules are evaluated in `schedule.timezone` (previously always UTC);
  - after downtime a cron/interval job runs **once** (`misfire_policy: run_once`) instead of replaying every missed
    tick; `misfire_policy: catch_up` restores replay;
  - `overlap_policy` (`allow` default, `skip`, `queue`) is now enforced;
  - Python installs: the default `uv sync` is lean; the scheduler/worker need `--extra full`
    (`uv sync --dev --all-extras` for development; the Dockerfiles already do this);
  - `hydra-ctl` exit codes: 3 unreachable, 4 not found, 5 `run --wait` non-success (not found used to be 1).
- [ ] `AGENTS.md`: the heading `Hydra lite edition (hydra_lite/, branch feat/hydra-lite)` still says "branch"; drop
  the branch wording and the "Still to do" tail when merging.
- [ ] Secrets scan of the diff (no tokens in fixtures; `tests/fixtures/lite_v1.db` is a synthetic database).
- [ ] `docs/investigations/` is not in the diff.

## After the merge

- Merge the release PR that release-please opens. Check the run created the tag `vX.Y.Z`, the four GHCR images, and a
  `hydra_jobs-X.Y.Z` sdist/wheel on the Release.
- Smoke the published wheel on a clean machine: `uv tool install hydra-jobs --from <wheel URL>` then
  `hydra-ctl lite doctor`.

## Rollback

The lite code is additive (a new package, new tests, docs), so the risky parts are the shared-code changes. They are
in separate commits and can be reverted individually: the dependency split (`build:`), timezone-aware cron and the
misfire/overlap enforcement (`fix(scheduler)`), and the shared-module refactors (`refactor(scheduler)`). Reverting the
dependency split restores the previous install commands; a database created by lite is never touched by the full edition.
