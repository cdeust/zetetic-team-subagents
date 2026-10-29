# Native merge gate: attribution of the failed gates of 2026-10-27/28

Base: `origin/main` `91b78b5`. Question asked: does the native `merge` gate fail
because it does not wait ("fails after a few seconds")? Method: read the logs of
every failed `Pipeline` run of `cdeust/Cortex` (40), `cdeust/ai-architect-mcp-codebase`
(1) and `cdeust/ai-architect-mcp-spec` (2) created from 2026-10-27, attach each
failed `merge` or `review` job to the step and code path that made it red, then
change only what the logs support.

Replay: `gh run list --repo cdeust/<repo> --workflow Pipeline --status failure
--created ">=2026-10-27"`, then `gh api repos/cdeust/<repo>/actions/runs/<id>/jobs`
and `gh api --allow-escape-sequences repos/cdeust/<repo>/actions/jobs/<job>/logs`.

## Attribution (43 failed runs, 48 failed merge/review jobs: 41 rows below + 7 `merge` jobs red downstream of a red `review`)

| Class | Runs | Failing step and code path | Verdict |
|---|---|---|---|
| Tests not green | 22 merge + 2 runs with no gate job | `merge` "Require completed tests and review": `unit`, `environment` or `install` failed, so `regression`, `e2e` and the matrix are skipped (`::error::unit: failure, needs success`). 14 of the 22 are named `merge pending review` because Codex was also pending | Correct red. The cause is the test job, not the gate |
| Unresolved review findings, `review` job | 3 (codebase 40642626192, spec 40614484791 and 40617164871) | `review` "Require completed Codex reviews": `state=blocked`, `reason=review_unresolved`, `reviews_complete=false`: one review has unresolved findings while the other is still `running`. `review_evidence` ranks blocked above pending, `main()` returns 1 | By design: `ci_codex_review_resume._waited(review, READINESS)` reruns the `review` job when both reviews are complete |
| Unresolved review findings, `merge` job | 11 Cortex runs (40434060283, 40442443055, 40501048565, 40506215105, 40509143935, 40527744161, 40630723227, 40675208580, 40695584810, 40749419955, 40750766726) | `merge` "Require complete Codex reviews": `state=blocked`, `reviews_complete=true`, strict table `{"blocked": 1}` | Correct red while findings are unresolved. Recovery route: `Codex.yml` cron `*/5` (thread resolution has no Actions event) then `resumption_plan` returns `merge` once the proof is `success` |
| Pending read as failure | 1 (Cortex 40444948084) | `review` "Require completed Codex reviews": `state=pending`, exit 2, `CODEX_COMPLETION_ONLY: true` but no `--allow-pending` in the executed script | Old pipeline. `--allow-pending` entered the template with e019aad (2026-10-27 23:49), after this run (03:53). Zero cases on the current template |
| Malformed evidence | 1 (Cortex 40522795315) | `review`: `state=blocked`, `reason=protocol`, `security_review` all null | Not reproducible: the summary comment body at 14:55 is gone. No change |
| PR no longer open | 1 (Cortex 40548981339) | `review` reader `_eligible`: `pr_eligibility`. PR 805 merged at 17:35:00, the step ran at 17:38:20 | Harmless, the PR is merged |
| Deliberate hold | 1 (Cortex 40583904933) | `merge` "Verify live PR eligibility": PR 811 renamed to "do not merge: ..." at 21:15:40, head still `6fec2753` until 21:35:51. The message said "closed, draft, held, or no longer at the tested head" | Correct red, but unreadable: it looked like a moved head |
| Old Claude review step | 1 (Cortex 40425805584) | `review` "Validate review execution": `cannot read execution file` | Profile removed from the native template |

The 41 rows count each failed job once at the step that made it red. The other 7
of the 48 jobs are `merge` jobs that failed at "Require completed tests and review"
only because `review` was already red in the same run (`review: failure, requires
completion`), so they are counted in the `review` rows: Cortex 40425805584,
40444948084, 40522795315 and 40548981339; codebase 40642626192; spec 40614484791 and
40617164871. Run 40548981339 never reached "Verify live PR eligibility", so it does
not support the diagnostics change; only 40583904933 does.

Findings that matter:

- No failure is a gate that gave up on a result that was about to arrive. The
  seven-second red jobs report a final verdict on results the previous jobs had
  already produced.
- Zero `head_moved` case on the current template. `pipeline.yml` sets
  `cancel-in-progress` for `pull_request`, so a new push cancels the older run
  before its `merge` job starts (`merge` runs only when `!cancelled()`).
- Zero pending flip (review `success`/non-pending, then merge strict step
  `pending`, exit 2) on the current template. If it happens, the job is red under
  the name `merge` and `resumption_plan` reruns it once the proof is `success`
  (`_waited(merge, MERGE)` with `proof.state == "success"`).

## What changed, and what was refused

Changed: the merge job's "Verify live PR eligibility" step names the first failing
condition (not open with its state, draft, head moved with both SHAs, held by
title, held by label). The set of conditions that fail is identical, so no gate
decision moves. Tests: `tests/test_ci_native_gate.py`. Receipt entry:
`merge-condition-diagnostics` in `templates/ci/native/source.json`; `merge`
moves from `jobs` to `adapted_jobs`.

Not changed, with the reason:

- A `merge superseded` job name for a moved head. GitHub evaluates
  `jobs.<job_id>.name` before any step runs, from `needs` only, so a live head read
  inside `merge` cannot choose the name; it would need a new upstream output and an
  edit of the pinned reader. No run shows the case, and cancellation covers it.
- A second job state for a pending flip. Exiting 0 from a job named `merge` while
  the live state is pending would let `resolve` squash-merge with a review running.
  The recovery already exists and is event driven.
- `resolve` in `pipeline-post-merge.yml`: no failure traces to it, so it is
  unchanged. Two characterization tests run its inline source and pin the invariant
  this change must not break: a run whose PR head moved raises `PostMergeError` and
  sends no `PUT`; `merge pending review` returns `run_tests=false` and sends no `PUT`.
  They are green on `origin/main` by construction (the fail-before checker reports
  them `VACUOUS`, exit 0). `tests/test_ci_post_merge.py` exercises
  `tools/ci_post_merge.py`, which has no `merge pending review` branch, so the native
  resolver had no test of its own.
- `claude-review.yml` `allowedTools`. Of 28 `claude[bot]` comments matching denial
  keywords, 17 come from `PR Review` runs and 8 from `Claude Code` runs (3 carry no
  run link). In the 17: 8 report that the sandbox blocked writing a long
  `gh pr comment` body to a temp file, 3 that `pytest`/`ruff`/`uv` needed approval,
  3 that `WebFetch`, `curl` or an outbound fetch was denied; the rest only discuss
  tools while reviewing workflow code. The list already equals the `allowed-tools`
  of `/review-pr` plus the inline-comment tool. Test and lint runs are outside the
  job's role (it checks out `main` with `contents: read`); `WebFetch` is excluded
  on purpose (prompt injection). A `--body-file -` instruction for long bodies is
  plausible but cannot be verified outside a hosted run. Method: `gh api
  repos/cdeust/<repo>/issues/comments?since=2026-10-27T00:00:00Z` filtered on
  `claude[bot]`, then `actions/runs/<id>` `.path` from the "View job" link.
