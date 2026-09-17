# Shared host gates

- [x] Reproduce Codex apply_patch source-hint no-op.
- [x] Implement common gate entry point and isolated package.
- [x] Normalize pre-tool events; freeze staged content for commit checks.
- [x] Install local Codex package through native CLI without modifying hook trust.
- [x] Complete post-tool target handling, tests, source sync and independent review.
- [x] Run full test suite: 40 suites passed, zero failures.
- [x] Complete coverage and staged checks.
- [x] Publish [PR #139](https://github.com/cdeust/zetetic-team-subagents/pull/139).
- [ ] User reviews native Codex hook trust and verifies a new session.

The first full run exposed scripts/test-agent-id-propagation.sh cleanup deleting
an active worktree when TARGETS was empty. Restored from packaged snapshot and
added a nonempty-target guard. Revalidate the full run, not its interrupted result.

## Review and validation

- `bash tests/run-all.sh`: 40 suites passed, zero failed.
- `python -m coverage run -m pytest -q`: 1,429 passed.
- `python -m coverage report`: 83%, above the configured 80% floor.
- Strict staged sourcing: zero errors and warnings.
- Canonical/package synchronization: passed; ShellCheck at warning severity passed.
- Independent adapter/staging/target review: approved after corrections.
- Codex CLI 0.154 accepted and installed local zetetic-gates 1.1.0; cached
  files match the source package. This is a local preview, not a released version.
- Native trusted session execution remains pending owner hook review.

The cleanup regression test now survives an empty target array. The successful
full rerun supersedes the interrupted run that deleted the initial worktree.

Final review found quoted Git executables bypassing dispatch. Add regression coverage before accepting the revised head. CI also requires the PR number in the feature commit subject and changelog.
