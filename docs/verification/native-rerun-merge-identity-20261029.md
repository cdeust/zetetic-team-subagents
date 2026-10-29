# Native rerun merge-job identity

Source: [cortex-vision PR5 finding4408735600](https://github.com/cdeust/cortex-vision/pull/5#discussion_r4408735600), read through GitHub REST on 2026-10-29. Canonical pipeline.yml has one job ID `merge`, whose display name depends on the review output.

An initial review API failure leaves a failed `merge`. Re-running failed jobs before reviews finish produces a successful `merge pending review`. Folding both names separately retains the historical failed merge and prevents successful review completion from resuming the review job.

The canonical event reader now uses `merge` as the folding key for both names. It keeps the original newest job record and display name, so the existing policy still distinguishes a pending review from a failed merge. Duplicate aliases within one authenticated attempt fail protocol validation. No additional API reads, permission changes, timing thresholds, or rerun policies are introduced. Complexity remains linear in the authenticated job-history rows.

## Reproduction

Command: `python3 -B -m unittest discover -s templates/ci/native/assets/scripts/tests -p test_ci_codex_review_event_attempts.py -v`

Before the production fix:

```text
FAIL: test_pending_merge_supersedes_failed_merge_display_name
AssertionError: {'action': 'none'} != {'action': 'review', 'job_id': 220}
FAIL: test_merge_aliases_in_same_attempt_cannot_hide_failure
AssertionError: ValueError not raised
Ran 16 tests
FAILED (failures=2)
```

The first test's current-only control already resumed review job20 and made one rerun request; the history case must resume review job220 and make one request. Other new contracts cover a newer genuine merge failure, unrelated historical failures, and a newer legitimate merge rerun target. The reverse-transition fixture initially reused its mutated pending record; it was corrected to use a fresh merge record before final verification.

## Final verification

- `python3 -B -m unittest discover -s templates/ci/native/assets/scripts/tests -p 'test_ci_codex_review_*.py'`: **101 tests, OK**.
- `python3 -B -m pytest -q tests/test_ci_native_renderer.py tests/test_ci_native_resumption.py tests/test_ci_native_cli.py tests/test_ci_native_schedule.py tests/test_ci_native_no_schedule.py`: **28 passed**. This executes the native decision/coordinator fixtures through their delivered integration path and verifies exact source-receipt hashes.
- `bash tools/tests/render-ci/run-tests.sh`: **7 passed, 0 failed**, including unchanged legacy workflow rendering.
- `git diff --check`: exit0.

The expected intermediate source-receipt mismatch was corrected with updated delivered hashes and an inverse adaptation that continues verifying the original pinned upstream source hash.

These are local fixture and rendering proofs. Hosted acceptance, fleet publication, and root review remain with the orchestrator; no remote writes were performed by this worker. The repository-wide suite is owned by root for the combined change. Cortex recall/methodology/remember and native Claude review commands were not exposed by this worker host.

## Resources

Worktree: `.claude/worktrees/native-rerun-names-20261029`, branch `fix/native-rerun-job-names`, from origin/main101c6937030f37d4c5ff76719729951822984c12. Creation hook registered it under the root session owner; root confirmed ownership and requested the ledger remain unchanged for handoff and later disposal. No scratch downloads or long-running test processes were created.
