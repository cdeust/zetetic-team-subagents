# Review bot: tools of its procedure, review requirements, named failures (2026-10-29)

## Observed

- PR #207 and #208, `review` job, step `Review`
  (jobs 123184947568 and 123200590300): the result object of the action reads
  `num_turns: 3`, `duration_ms: 9466` and `9403`, `permission_denials_count: 0`,
  and `claude[bot]` posted "## Code review No issues found. Checked for bugs and
  CLAUDE.md compliance." on both. #207 made the merge eligibility step fail
  open; the review verdict on #207 (issuecomment-6484489154) found that, the
  bot did not.
- Every successful `Review` since 2026-10-27 is as short: 15 runs scanned
  (40603153044 to 40797450781), 2 to 12 turns, 0.04 to 0.14 USD, against
  1.32 USD for one full run of the procedure below.
- PR #191 and #192 (runs 40186210241 and 40201492297, 2026-10-25): the first
  two runs in which the `Review` step executed at all (the earlier runs skipped
  the bot steps, "bootstrap workflow change"). Result `subtype: success`,
  `is_error: true`, `duration_ms: 434`, `num_turns: 1`, `total_cost_usd: 0`,
  `modelUsage: {}`. The step inputs, the action SHA (a5a423f, v1.0.256), the
  Claude Code version (2.1.306) and the secret (`CLAUDE_CODE_OAUTH_TOKEN`,
  updated 2026-10-21T15:36:39Z, unchanged since) are identical to the
  successful runs from 2026-10-27 on; the log diff of the two steps differs
  only in the PR number and run id. With `show_full_output: false` the action
  prints no error field, so the class of that failure (401 as in
  anthropics/claude-code-action#1614, a usage limit, an outage) is not in any
  artifact. This change makes the next one name it.

## Reproduction (local, Claude Code 2.1.312, plugin `code-review` from
anthropics/claude-plugins-official f8c5e7a, PR #191 at ec74702, no `--comment`)

Narrow, as on main (`--allowedTools "mcp__github_inline_comment__create_inline_comment"`):
5 turns, 14.9 s, 0.11 USD. Tool calls: `gh pr view`, `gh pr diff`; no `Agent`
call. Final text: "No issues found. Checked for bugs and CLAUDE.md compliance.
[...] I didn't check whether the repo has a CLAUDE.md. [...] I also didn't
launch the review subagents, because there was no code to review."

Widened, as in this change (prompt and tools of the rendered `Review` step,
`--comment` removed so nothing was posted): 20 turns and 49.5 s to its first
result, 1.32 USD in all (the session resumed as each background agent
returned). The
skill launched its agents, read the changed file and the workflow it describes,
read the log of run 40186210241, sent each of the two findings to a validation
agent, which rejected both (9 `Agent` calls: eligibility and CLAUDE.md
finder on haiku, summary and two CLAUDE.md compliance on sonnet, two bug
reviews and two validations on opus). It tried `bash tests/run-all.sh`, which this
allowlist refuses, and therefore withheld the unqualified "No issues found"
and named the step it could not run, as the prompt requires.

## Tests

`tests/test_ci_template.py`: the allowlist is exactly the procedure, reading
and test tools and holds nothing that edits; the prompt carries the head SHA
and each requirement; the dependency step is conditioned on
`requirements-dev.lock` and uses `--require-hashes`; the failure step, run with
bash on a fixture execution file, prints
`subtype=success is_error=true api_error_status=401 terminal_reason=api_error`
and not the result text, and reports a missing execution file. Against the
template of origin/main 1b7ad1f: 5 failed, 14 passed. With this change:
19 passed; the rendered `.github/workflows/pipeline.yml` passes actionlint
1.7.12.

## Limits

- This pull request changes `.github/workflows/pipeline.yml`, so its own run
  skips the bot steps (Review guard, "bootstrap workflow change"); the first
  review with these tools is the next pull request after the merge.
- The reviewer runs tests only where the runner can: this repository's suite
  needs its `requirements-dev.lock`, installed by the new step; a repository
  whose suite runs through another command than the listed runners gets the
  logs of its test jobs, not a run.
- The owner rule of 2026-10-21 names two native review skills, `/code-review`
  and `/security-review`; this pipeline runs the first only, as before.
