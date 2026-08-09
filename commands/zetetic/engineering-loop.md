# Zetetic Engineering Loop

Mandatory entry point for any feature, fix, or dev request that will touch code. Drives one
request through recall → refine → implement → verify → benchmark → review → remember, with
every zetetic gate run rather than merely stated.

**No code is written outside this loop.** Restored per ADR-003's own finding: the standard was
"stated but not run as a loop", and an opt-in loop is not a loop. If you are about to edit a
file and have not run these steps, stop and run them.

Designed to run under `/loop`: `/loop /zetetic:engineering-loop <request>`. A single pass is
`/zetetic:engineering-loop <request>`.

## Instructions

### 0. Name the check — before anything else

State the pass/fail signal that will close this loop: a test, a build exit code, a linter, a
script diffing against a fixture, a benchmark number, a screenshot comparison.

**If no check can be named, the request is not ready to implement.** Go back to scoping. Do not
proceed to step 1 with "I'll know it when I see it" — that makes the user the verification
loop, which is the failure this loop exists to prevent.

The check must be an **external signal**: something that runs and returns a result. Never the
model re-reading its own output.

### 1. Recall — what is already known

```
cortex:recall({ "query": "<the problem/area>", "max_results": 15 })
cortex:recall({ "query": "failed attempts lessons mistakes <topic>", "max_results": 10 })
```

Past sessions may already have investigated this. If a past attempt failed, understand why
before repeating it. If a decision was recorded, respect it unless there is new evidence. If
recall contradicts the plan, pause and resolve the contradiction before writing code.

### 2. Refine — bind every name to a real artifact

Run `/refine <request>` when the request is vague, or do its work inline: resolve every named
system, component, or concept to the actual file, module, or symbol. A name that maps to
several candidates is resolved with evidence — grep, git history, recall — never guessed.

Output of this step: symptom, goal, non-goals, and the acceptance criteria from step 0 stated
as checkable commands.

### 3. Investigate — never speculate about unopened code

Read the files that matter. Never claim anything about code you have not opened. A claim of
absence ("this is dead", "no such rule exists", "nothing calls this") requires tracing to the
primary artifact — the call path to a production entry point, the file itself, the shipped
binary. One grep is not a search.

### 4. Implement — the smallest change that satisfies the criteria

Only what is requested or clearly necessary. No abstractions for hypothetical futures, no
error handling for impossible states, no cleanup of surrounding code, no docstrings on code you
did not change. Validate at system boundaries only.

Root causes, not symptoms. Fix where the invariant breaks, never at the throw site.

### 5. Verify — run the check from step 0

Run it. Read the result. Iterate until it passes.

Report **evidence, not assertion**: the command run and what it returned. If tests fail, say so
with the output. If a step was skipped, say that. "It works" is not a result.

### 6. Benchmark — when a measurable exists

If the repo has a benchmark, run it before and after and record the delta with the exact change
that caused it. A change with no measured delta does not ship as an improvement.

Never tune a rule against the sample used to measure it. If a fix was made because a
measurement exposed it, rebuild the measurement on fresh, held-out data.

### 7. Review — a fresh context, not self-critique

Run `/code-review` on the diff, or delegate a reviewer that sees the diff and the criteria but
not the reasoning that produced them.

Instruct the reviewer to flag only what affects correctness or the stated requirements — a
reviewer asked for gaps will find some regardless, and chasing all of them produces
over-engineering.

Note the model-specific rule (`~/.claude/rules/model-behavior.md`): on Opus 5, do **not** spawn
a subagent to verify your own work; on Fable 5, a fresh-context verifier is recommended.

### 8. Remember — record what a future session needs

One self-contained fact per entry, readable without this session's context:

```
cortex:remember({
  "content": "<decision + rationale | rejected approach + root cause | lesson as an actionable rule>",
  "tags": ["archival", "<category>", "<area>"],
  "agent_topic": "<scope>",
  "source": "<bug-fix|feature|benchmark|lesson>"
})
```

Session state and checkpoints go to the memory block, not here. Do not record what the repo or
git history already says.

## Stopping conditions

- **Done**: the check from step 0 passes, evidence is shown, and the learning is recorded.
- **Blocked**: input only the user can provide, a destructive or irreversible action, or a real
  scope change. Ask and end the turn — never end on a promise of work not done.
- **Off track**: after two failed corrections on the same issue, the context is polluted with
  failed approaches. Stop, clear, and restart with a prompt incorporating what was learned.

## Contract violations — answers that are never acceptable

These are refusals, not preferences. An agent that produces one of them has broken the
contract, and the owner should not have to say so again.

1. **"Pre-existing" / "outside the blast radius" / "I filed an issue for it" — one refusal
   wearing three faces.** There is no blast radius for breakage, and filing is not an action.
   You touch something and it breaks, you fix it on the way: no discussion, no scoping debate,
   no matter who broke it or when. A red test, a failing check, a violated invariant in code you
   passed through is yours the moment you saw it. **You do not open issues — the user is the
   only one who does.** An issue you file is a way of choosing not to work, and you do not get
   to choose: you act, you do, you fix. If something genuinely cannot be fixed now, it goes in
   the report to the user, who decides whether it becomes an issue.
2. **A skip is a violation.** "Out of scope for this PR", "deferred to a follow-up", "too large
   for one session", "I judged this multi-week" — none of these end a task. Work that does not
   fit is CHECKPOINTED and CONTINUED, never abandoned with a note. The only legitimate stop is
   input that only the user can give.
3. **A failing PR is a violation.** Red CI is not "done pending checks". **A delegated contract
   ends when it is fulfilled, not when a report is written**: for work that lands in a
   repository, fulfilled means the PR is **green, mergeable, and verified**. Until then you keep
   working — you do not stop, do not negotiate the scope down, do not wander onto adjacent work,
   and do not hand back a red deliverable with an explanation attached.

**Enforce these on anything you delegate.** The rules that bind you bind any agent you spawn;
check its output the way yours would be checked, and reopen the contract when they were not met.
And **an agent's final report is not proof that it stopped** — measured twice on 2026-08-09: two
subagents kept writing into the working tree for hours after delivering a report that read as
final, one silently starting an architectural change it had itself declared out of scope, both
with the deliverable's own tests still red. Check the process list, not the report, before
calling a tree clean or a measurement valid.

Corollary: **finish what you open.** An abandoned branch, or a green PR left unmerged with no
owner, is the same failure as leaving CI red.

## What this loop refuses

Code produced directly from a prompt. Work reported as done without evidence. A merged change
that is unreachable from the production path — test-gated, flagged off, uncalled — presented as
progress. A benchmark tuned until it agrees. A negative claim asserted from an incomplete
search.

$ARGUMENTS
