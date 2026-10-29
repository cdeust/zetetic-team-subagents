# Native review polling policy

- [x] Read native sources and recall prior constraints.
- [x] Run final regression tests against the base renderer: 6 failed, exit 1.
- [x] Add native-only schedule opt-out, preserving other bytes and default assets.
- [x] Run renderer contracts and staged source/craftsmanship checks.
- [x] Prepare isolated source PR; consumer installation belongs to the orchestrator.

## Review

`python3 -B -m pytest -q tests/test_ci_native*.py tests/test_ci_renderer.py`:
`80 passed, 33 subtests passed` (exit 0).
`bash tools/tests/render-ci/run-tests.sh`: `render-ci: 7 passed, 0 failed`.
The existing source-receipt test verifies byte-identical default native delivery.
The new contract compares every opt-out file byte for byte, then parses Codex
YAML to verify only the schedule trigger was removed. CLI tests cover dry-run,
native-only rejection, delivery and restoration; template drift fails closed.

`ZETETIC_PROFILE=strict bash tools/zetetic-checker.sh --staged` and
`bash tools/craftsmanship-checker.sh --staged`: zero errors and warnings.
`bash tools/doc-count-check.sh`: 32 claims, zero problems.
`bash tools/doc-command-check.sh`: 17 commands, zero missing.
`git diff --cached --check`: exit 0.

Local code/security review: exact-block validation precedes all destination
writes and uses the existing transactional writer. No permission, model, job or
consumer workflow changes. Processing remains linear in the fixed native asset
size. Resolving threads alone requires manual dispatch or a later completion
event when polling is disabled. Hosted CI and actual agent execution belong to
the orchestrator after publication; local tests do not prove hosted acceptance.
