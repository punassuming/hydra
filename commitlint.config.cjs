// Enforces Conventional Commits. Kept in sync with the type list
// release-please-config.json's changelog-sections actually parses — a type
// commitlint accepts that release-please doesn't (or vice versa) would let
// commits pass CI while still being invisible to the version-bump/changelog
// pipeline. See AGENTS.md's "Working Agreements" section for the full
// rationale and CONTRIBUTING.md for examples.
//
// .cjs extension is required, not just a style choice: wagoid/commitlint-
// github-action runs this in a Docker container whose OWN root package.json
// declares "type": "module" — since there's no package.json anywhere under
// this repo to tell Node otherwise, a bare "commitlint.config.js" here gets
// loaded as an ES module (and `module.exports` throws a ReferenceError).
// ".cjs" forces CommonJS regardless of any package.json "type" field.
module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      ["feat", "fix", "perf", "revert", "docs", "deps", "chore", "refactor", "test", "build", "ci"],
    ],
  },
};
