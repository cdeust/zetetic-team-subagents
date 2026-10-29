# Native review tools and the Fix guard, 2026-10-29

Base: `5f5537a` (#223). Three changes: the native `claude-review.yml` asset
gets what #211 gave the legacy `Review` step (E1), the legacy `Fix` step runs
only on a failed test job (E2), and the native `claude.yml` asset serializes
owner mentions per thread again (E3).

## E1: what the native review could not do

The brief assumed the native review repeated #207 (9 s, no subagent, "No issues
found"). The runs say otherwise. The 25 native reviews read on 2026-10-29
(every successful `claude-review.yml` run among the last ten of each native
repository that reached Claude; the 39 others stopped at the action's workflow
validation skip because their PR changed a workflow) ran long and launched
subagents:

| repository | run | turns | s | permission denials | USD |
|---|---|---|---|---|---|
| Cortex | 40850394585 | 21 | 218 | 1 | 3.92 |
| Cortex | 40849374046 | 26 | 294 | 4 | 4.85 |
| Cortex | 40847804179 | 26 | 376 | 4 | 5.78 |
| Cortex | 40845641264 | 29 | 199 | 8 | 3.59 |
| Cortex | 40844703432 | 24 | 296 | 7 | 3.93 |
| Cortex | 40844226128 | 22 | 391 | 8 | 4.90 |
| Cortex | 40843804839 | 23 | 232 | 6 | 2.85 |
| Cortex | 40842880530 | 26 | 286 | 4 | 3.24 |
| Cortex | 40842083032 | 26 | 236 | 4 | 2.46 |
| cortex-viz | 40839074830 | 21 | 102 | 5 | 1.04 |
| cortex-viz | 40839069338 | 19 | 189 | 4 | 1.85 |
| cortex-viz | 40839064342 | 20 | 120 | 6 | 1.30 |
| cortex-viz | 40839057479 | 13 | 88 | 3 | 0.74 |
| cortex-viz | 40839053046 | 18 | 90 | 10 | 0.78 |
| cortex-viz | 40839046719 | 19 | 100 | 9 | 0.94 |
| cortex-viz | 40825976219 | 24 | 134 | 9 | 1.41 |
| ai-architect-mcp-spec | 40824942080 | 18 | 234 | 6 | 2.30 |
| ai-architect-mcp-spec | 40818220127 | 18 | 186 | 10 | 1.90 |
| ai-architect-mcp-spec | 40637091722 | 17 | 201 | 4 | 2.10 |
| ai-architect-mcp-spec | 40635236093 | 17 | 201 | 7 | 2.19 |
| ai-architect-mcp-spec | 40630903032 | 21 | 270 | 10 | 3.38 |
| claude-mods | 39744671276 | 9 | 57 | 0 | 0.19 |
| ci-autonome | 40864021078 | 22 | 273 | 6 | 4.35 |
| ci-autonome | 40862246883 | 25 | 173 | 7 | 1.62 |
| ci-autonome | 40861917132 | 22 | 332 | 10 | 2.96 |

Values are the `result` record each run prints (`num_turns`, `duration_ms`,
`permission_denials_count`, `total_cost_usd`). The faults are elsewhere:

- 24 of 25 runs were denied 1 to 10 tool calls. The summary of Cortex PR834
  (run 40845641264, comment 6492314307) lists the five reviewer agents as run,
  then: "I read the code but did not run the tests: the sandbox does not allow
  `pytest` or `uv sync` in this job." The allowed tools were the inline
  comment and `gh pr comment/diff/view`; `--permission-mode auto` left every
  test runner to the classifier.
- The three ci-autonome runs (private repository) logged "The github_ci MCP
  server requires 'actions: read' permission". The pinned action installs its
  `github_ci` tools only when the workflow token can read Actions
  (`src/mcp/install-mcp-server.ts`, 8041f1d), and the job did not declare it.
  The reviewer could not read the Pipeline logs. In the native profile the
  review is its own workflow, so `github.run_id` holds no test jobs; the prompt
  names the Pipeline run of the head and the `github_ci` tools that read it.
- A failed review had no step naming its error class (#211 added one to the
  legacy pipeline), and the prompt did not tie the verdict to completed steps.

The `Agent` tool is not gated by `--allowedTools`: with CLI 2.1.312,
`claude -p --setting-sources project --allowedTools Read` launched a subagent
that answered "pong", with no permission denial. Listing `Agent` declares the
five subagents of `.claude/commands/review-pr.md`; it does not unlock them.

The change (adaptation `native-review-procedure-tools` in
`templates/ci/native/source.json`): `actions: read`; hashed install of
`requirements-dev.lock` before the review (this is the lock of the `main`
checkout; the action checks out the PR head afterwards; Cortex, which uses
`uv.lock`, gets no dependencies from this step); `id: claude_review` and
`show_full_output: false`; three prompt lines after `/review-pr` (head SHA, the
whole diff, changed files and their tests, the Pipeline logs through the
`github_ci` tools, the tests that cover the change, no findings reported only
when every step ran); the allowed tools of the procedure, read-only git, the
three `github_ci` tools and the test runners of #211, nothing that edits or
pushes; and the `Name the review failure` step of #211, byte for byte.
`tests/test_ci_native_renderer.py::without_review_procedure_tools` removes each
block and restores upstream's allowed tools: the result hashes to the recorded
`source_sha256` `4b2455d3...`.

## E2: Fix on a green run

Run 40862677865 (PR #223, head `4c9258b`): contract, unit, regression, e2e,
three environment and three install jobs all `success`. In `review`, the guard
set `fix=true` (the default for a head not authored by Claude), "Collect the
failed jobs of this run" returned an empty list, `Review` passed, and `Fix`
ran from 11:16:50 to 11:18:06 and pushed e1dcc25 (a review finding applied to
`ci_codex_review_event_source.py` and `source.json`). The Pipeline run of
e1dcc25 (40864319948) was created at 11:18:07, and `cancel-in-progress` then
cancelled 40862677865. The cancellation followed the push; the condition that
would have stopped this run is the failure count, which was zero.

The change in `templates/ci/pipeline.yml`:

- `review` needs `contract` too. A failed contract skips the five categories,
  and the guard reads the results of every test job from `toJSON(needs)`.
- The guard sets `fix` to `any(.[]; .result == "failure")` for every head. A
  cancelled, skipped or timed-out job is no fault to repair. Claude heads keep
  `review=false`. The bootstrap skip is unchanged: a PR that changes
  `.github/workflows/pipeline.yml` and is not authored by the owner sets both
  outputs false. The owner exception of #218 (9242772) stays; this change does
  not widen the skip to every `.github/workflows/*` file, which would revert
  that merged decision.
- `Fix` runs if `success() && !cancelled() && steps.guard.outputs.fix == 'true'`.

## E3: one owner mention at a time per thread

Cortex #822 (3aef5b59, merged 2026-10-28) gave the owner mention workflow a
job `concurrency` (`claude-mentions-${{ github.event.issue.number }}`,
`cancel-in-progress: false`, `queue: max`) so two bot sessions never push one
branch at once. The native template's `claude.yml` comes from Cortex
`8e7375bf`, which predates #822; #218 ported the permissions of #822 but not
this block, so a native re-render removes it from Cortex. The asset now carries
the same group and `cancel-in-progress: false` between the job condition and
`runs-on`, before the step "Authorize owner fix target", which it does not
change. `queue: max` is left out: the pinned actionlint 1.7.12 rejects the key
("unexpected key \"queue\" for \"concurrency\" section"), although GitHub
accepted Cortex's file (its `claude.yml` runs were created after #822). Without
it a thread keeps one pending request and a newer one replaces it. Adaptation
`owner-mention-concurrency`; the reversion still hashes to `c7604362...`.
Red: `test_owner_mentions_run_one_at_a_time_per_thread` 1 failed, 9 passed.

## Validation

- Red, on the templates of `5f5537a` with the new tests: `30 failed, 93 passed`
  (7 E1 tests in `tests/test_ci_native_review_tools.py`, 22 E2 cases in
  `tests/test_ci_pr_safety.py`, 1 in `tests/test_ci_template.py`).
- Green: `python3 -m pytest -q tests/test_ci_*.py`, 582 passed, 39 subtests
  passed; `bash tools/tests/render-ci/run-tests.sh`, 7 passed.
- `actionlint`: exit 0 on the three rendered workflows of this repository and on
  the six workflows of a native render.

## Hosted acceptance still required

No hosted run of either change: the native review with the new tools, the
`actions: read` grant on a private repository and a red run reaching `Fix` all
need a real pull request after the consumers are re-rendered.
