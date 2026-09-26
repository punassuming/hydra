// Enforces Conventional Commits. Kept in sync with the type list
// release-please-config.json's changelog-sections actually parses — a type
// commitlint accepts that release-please doesn't (or vice versa) would let
// commits pass CI while still being invisible to the version-bump/changelog
// pipeline. See AGENTS.md's "Working Agreements" section for the full
// rationale and CONTRIBUTING.md for examples.
//
// CommonJS on purpose: there is no package.json at the repo root declaring
// "type": "module", so a bare .js file here is loaded as CommonJS by
// default (ui/'s own package.json only governs files under ui/).
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
