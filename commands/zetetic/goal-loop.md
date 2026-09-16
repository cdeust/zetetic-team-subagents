# Goal Loop

One tick of the goal cycle: read the active goal file, run the skill the ledger calls for,
write the ledger, stop. Designed to run under the native `/goal` (the evaluator reads the
verify-goal summary in the transcript) or under `/loop` (a timed tick). A single pass is
`/zetetic:goal-loop <slug>`.

The four skills are portable (`plugins/zetetic-loop`): the same files drive Codex and
Gemini CLI, where they are invoked as `$goal`, `$plan`, `$verify-goal`, `$refine-goal`.

## Instructions

1. **Locate the goal.** `$ARGUMENTS` is a slug, a request, or empty. A slug maps to
   `.zetetic/goals/<slug>.md`. A request with no matching file runs the `goal` skill,
   resolved with `tools/skill-runner.sh goal`, and stops after the file is written. Empty takes the only file
   with status `active`; refuse if there are several.

2. **Read the status and the last ledger entry**, then run the next phase. Resolve every
   skill file with `tools/skill-runner.sh <name>` (never a path relative to the current
   repository; the plugin root is not the working directory). Honour a model-tier escalation
   banner by spawning the named agent.

   | Status | Last entry | Run |
   |--------|-----------|-----|
   | draft | any | nothing; report that no check could be named |
   | active | none, or refine-goal | `plan` |
   | active | plan with verdict sound matching the current Plan revision | execute the first unexecuted step, then `verify-goal` |
   | active | plan with verdict unsound | `plan` again with the findings |
   | active | plan revision or verdict differs from Plan | stop; reconcile the plan before execution |
   | active | verify-goal | `refine-goal` |
   | met | any | nothing; report the achieving iteration |
   | blocked | any | report the recorded reason and preserve counters; repair a check error in the existing contract via `goal`; unavailable token accounting requires accounting to become available or the user to change the limit |
   | exhausted | any | nothing; report the residual unmet rows |

3. **Budget.** Apply the portable goal budget policy before dispatch. A new plan requires
   `iterations_used` below the finite limit; a sound current plan may finish its execution,
   verification and refinement at the last allowed iteration. Check reported cumulative
   tokens before every phase and command. A reached finite token limit sets `exhausted`;
   missing accounting for a finite token limit sets `blocked`. Do not reset counters or
   increase budgets.

4. **Print the verify-goal summary verbatim** whenever it runs. On Claude Code the native
   `/goal` evaluator decides from that line; nothing it cannot read counts.

5. **Stop after one phase.** Execution plus verification is one phase; other rows run one
   skill. The next tick, or an available native continuation, reads the new ledger entry.

A normal tick stops at `met`. To inspect a completed result for accidental success or
honor a request to tighten it, invoke `refine-goal` directly. If it reopens the contract,
resume goal-loop with the slug and the existing counters.

## Starting a loop

```
/zetetic:goal-loop make the auth tests pass without touching the fixtures
/goal verify-goal reports every criterion of .zetetic/goals/auth-tests.md met, with the command output in the transcript, or the file reports blocked or exhausted
```

or, time-driven:

```
/loop 10m /zetetic:goal-loop auth-tests
```

$ARGUMENTS
