# Contributing

## Commit messages (Conventional Commits)

Versioning, `CHANGELOG.md`, and GitHub Releases are generated automatically
by [release-please](https://github.com/googleapis/release-please) from
commit messages on `main` — see **Release process** below. For that to work,
commits merged to `main` need to follow
[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types that matter for versioning/changelog:

| Type | Effect | Changelog section |
|---|---|---|
| `fix:` | Patch bump (0.1.0 → 0.1.1) | Bug Fixes |
| `feat:` | Minor bump (0.1.0 → 0.2.0) | Features |
| `fix!:` / `feat!:` / a `BREAKING CHANGE:` footer | Major bump once past 1.0.0 (pre-1.0, see note below) | called out at the top of the entry |
| `perf:` | Patch bump | Performance |
| `docs:`, `chore:`, `refactor:`, `test:`, `build:`, `ci:` | No version bump | Miscellaneous (kept out of the changelog by default) |

Examples:

```
fix: correct duration calc when a run has no start_ts
feat(worker): add heartbeat liveness file for Go workers
docs: add Windows Service (NSSM) instructions
fix!: require domain header on all non-admin requests

BREAKING CHANGE: requests without x-domain now return 401 instead of
falling back to the "prod" domain.
```

This repo currently sits pre-1.0 (`0.x.y`); release-please is configured
with `bump-minor-pre-major: true`, so `feat:` bumps the minor version
(`0.1.0 → 0.2.0`) rather than the major version, consistent with SemVer's
guidance for initial development.

**Merge strategy matters here**: this repo merges PRs with a merge commit
(not squash), so it's each individual commit that reaches `main` that gets
scanned — write each commit message as if it stands alone, not just the PR
title.

## Release process

1. Every PR merged to `main` (with at least one `fix:`/`feat:`/etc. commit)
   causes the `release-please` workflow to open or update a single standing
   "release PR" — title like `chore(main): release 0.2.0` — containing the
   version bump (`pyproject.toml`, `ui/package.json`,
   `deploy/helm/hydra/Chart.yaml`, `.release-please-manifest.json`) and the
   accumulated `CHANGELOG.md` entry.
2. Merging that release PR (same as any other PR) triggers the workflow
   again, which tags the release (`vX.Y.Z`) and publishes a GitHub Release
   with the changelog entry as its notes.
3. Repeat — a new release PR starts accumulating the next round of changes.

No manual version bumping or changelog editing needed; just use Conventional
Commits and merge the release PR whenever you're ready to cut a release.

### Optional: PAT for the release PR to get CI-checked

By default the workflow uses `GITHUB_TOKEN`, which works but has one
limitation: PRs/pushes made with the default token don't trigger *other*
workflows, so the release PR won't automatically get `python-ci.yml`'s
checks run against it before merge (the code in it was already tested when
its component commits were merged, so this is a minor gap, not a
correctness risk).

To close that gap, add a fine-grained PAT (repo-scoped, `contents: write` +
`pull requests: write`) as a repository secret named
`RELEASE_PLEASE_TOKEN`; the workflow already prefers it when present.
