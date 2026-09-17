# PR 139 review corrections

## Plan

- [x] Reproduce selector overblocking and malformed post-tool quoting.
- [x] Restrict selector refusal to commit/push and preserve the parsed verb.
- [x] Preserve declared profiles and document intentional blocking policies.
- [x] Restore unchanged timeouts, restrict matchers, preserve marketplace Unicode.
- [x] Synchronize the standalone package and obtain independent review.
- [x] Complete full-suite and coverage verification.
- [x] Prepare and push the verified correction; remote checks are tracked on PR #139.
- [ ] Validate corrected definitions through trusted native Codex execution.

## Decisions

The shared runtime no longer injects a strict source profile. Staged prose
follows the project profile. Checker configuration/execution errors block,
because the checks did not complete. Shared Stop and outbound prose remain
blocking; these changes from legacy behavior are explicit in the documentation.

Commit and push both retain staged checking, matching the previous full-plugin
hook. The adapter forwards the parsed verb. This does not validate the contents
of already-created commits. Existing Claude push-specific gates remain separate.

Unchanged hook commands retain their original timeouts. The shared hooks use
host defaults and match only applicable tools; secret protection still covers
Read, Bash, Grep, Edit, Write and NotebookEdit.

## Completion ledger

| Changed area | Evidence |
| --- | --- |
| Git selectors and post-tool quoting | Six regression failures on dc3f811; initial parser correction passed all 29 tests. Expanded parser tests cover argument text and preserved verbs. |
| Profile, checker error and prose policy | Real full/standalone subprocess tests for absent, standard and strict profiles, malformed config, and staged prose. |
| Host dispatch and matchers | Independent focused run: 57 passed; supported secret tool set retained. |
| Claude timeouts | Independent comparison against pre-PR parent 77b4f78: no timeout differences for retained commands. |
| Standalone runtime | Canonical synchronization check passes. |
| Documentation and Unicode | Documentation count/command checks and diff whitespace check pass; marketplace retains literal Unicode. |

## Native-host evidence and limit

Codex 0.154.0 executed installed PreToolUse blocking and edit advisory hooks in
the correction session. The observations lack a source-file hash and raw event
payload, so they do not validate the corrected PR artifact. Codex loads
hooks/gates.json. The documented Bash/apply_patch command payloads match the
adapter. Corrected hook execution, including PostToolUse and Stop, still needs
native acceptance after hook review. No installed hook or trust setting was
changed by this correction.

## Local validation

On the corrected tree, all 40 discovered suites passed. The final Python
coverage run passed 1,534 tests and reported 83% against the 80% floor.
Strict staged source checking and staged craftsmanship checking reported zero
errors and warnings; staged redaction passed. Package synchronization and
documentation checks passed. Independent review found no correction defect.
