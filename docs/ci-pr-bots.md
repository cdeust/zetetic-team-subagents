# PR bot repair and merge checks

Edit `templates/ci/pipeline.yml`, then run `bash scripts/setup.sh render-ci .`.
The renderer copies the template with its Git blob identifier and preserves the
repository's `ci.json`. Each consuming repository needs the newly rendered copy.

The five test categories, the 90 percent line-coverage gate, and the three bare
runner environments remain the existing CI contract. The common Claude CLI pin
is 2.1.306, measured passing in [claude-mods PR45's unit job](https://github.com/cdeust/claude-mods/actions/runs/39773059845/job/119805310369).

## Review and repair

The review uses the official [Claude Code review plugin invocation](https://code.claude.com/docs/en/github-actions#run-a-skill).
The action's [allowed_bots input](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/action.yml)
permits only `claude[bot]` and `chatgpt-codex-connector[bot]` as bot actors. The
existing scoped tool permissions stay unchanged. This does not add a Codex job.

For an eligible human-authored head, Claude reviews and then fixes findings or
failed tests. A Claude-authored head skips duplicate review; it still runs the
fix step if any of the five test jobs did not succeed. When those jobs are all
green, it runs neither action. The guard refuses a checkout that has advanced
beyond the event's head, and a Git diff failure fails the guard.

Both mutating jobs (`review` and `merge`) use `always() && !cancelled()`: normal
test failures still reach repair and the explicit merge gate, but cancelling
the workflow prevents further repair or merge work. GitHub re-evaluates job
conditions during cancellation; `always()` alone keeps a job running
([cancellation reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation)).

The existing bootstrap exception remains: a PR changing
`.github/workflows/pipeline.yml` skips both bot actions. Dependabot remains
outside Claude's review scope. Draft and fork PRs remain ineligible.

## Merge and release

Merge requires the contract and all five test jobs to succeed. Review must
complete successfully; its only permitted skipped-job result is the existing
Dependabot exception. Failure, cancellation, timeout, and missing results block
the merge. A skipped bot step inside a successful review job preserves the
bootstrap and Claude-head behavior described above.

Immediately before arming auto-merge, the workflow rereads the PR and refuses a
closed or draft PR, the `hold` or `do-not-merge` label, a title containing
`do not merge`, or a head differing from the tested event SHA. Labels and the
title marker are matched without case sensitivity. The
[--match-head-commit option](https://cli.github.com/manual/gh_pr_merge)
also binds the merge request to that SHA, closing the head-change race between
the read and the merge command. A failed merge command stays failed even if an
auto-merge request was already armed. No administrator bypass is used.

The release tag job explicitly depends on all five successful test jobs and the
contract. Its deploy-key and existing-version behavior remains unchanged.

## Regression evidence

`tests/test_ci_pr_safety.py` executes the template's shell guards with fixture
Git and GitHub responses. It covers red Claude heads in every category, workflow
bootstrap skips, stale checkout rejection, unsuccessful job states, live PR
holds, exact merge arguments, and merge rejection. It performs no remote write.
Before the initial change, this suite reported 31 failures and 27 passes.
The two added cancellation-source regressions failed before the cancellation
veto was added and pass afterward; hosted cancellation remains a runtime
acceptance check.

The focused post-change suite includes the existing template, contract, and
coverage tests. Actionlint checks the template and rendered workflow; the
render-ci suite checks byte parity, idempotency, and preservation of `ci.json`.
These checks verify workflow behavior and structure. Hosted action execution and
native bot review remain the publication acceptance checks.
