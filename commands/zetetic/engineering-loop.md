# Zetetic Engineering Loop

Mandatory entry point for any feature, fix, or dev request that will touch code. Drives one
request through recall → refine → implement → verify → benchmark → review → remember, with
every zetetic gate run rather than merely stated.

**No code is written outside this loop.** Restored per ADR-003's own finding: the standard was
"stated but not run as a loop", and an opt-in loop is not a loop. If you are about to edit a
file and have not run these steps, stop and run them.

Designed to run under `/loop`: `/loop /zetetic:engineering-loop <request>`. A single pass is
`/zetetic:engineering-loop <request>`.

## Unattended intake — a text file in, a finished feature out

The user's only obligation is to write what they want. Everything after that is this loop's job,
including refusing its own sub-standard output.

**Intake.** `$ARGUMENTS` may be a request, the path of a file describing one, or empty. When
empty, read `features/` at the repository root and take the oldest `*.md` with no `## Delivered`
section. That file is the contract. **Ambiguity is not a reason to surface.** Resolve it the way
the ecosystem resolves it: read how the surrounding code already answers the question, pick the
answer that makes the feature work end to end, and state what you chose in the delivery. There is
no arbitration to hand back.

**Autonomy.** Runs under `/loop`. The user is asleep: they cannot answer, so do not ask; they
cannot babysit phases, so do not narrate them. Checkpoint, continue, and surface once — when the
feature is built, functional in the ecosystem, and delivered to standard. **That is the only
accepted outcome.** Not a partial feature, not a design proposal, not a question.

**On completion**, append a `## Delivered` section to the feature file: the PR link, the measured
acceptance evidence, and the proof it runs in the ecosystem. That file is what the user reads
when they wake up.

**Functional in the ecosystem** is the bar, and it is stricter than "merged". The feature is
reachable from the production path — not test-gated, not behind a flag nobody sets, not an
instrument. It runs against the real system it belongs to, with the surrounding components it
must cooperate with, and the evidence shows it working there: the command invoked, the output
returned, the state it changed. Code that compiles, passes tests and is unreachable has delivered
nothing.

## The standard the output must meet

Not "it works". Code leaving this loop is held to what the best engineering organisations ship:

- **No known bug.** Not "tests pass" — the failure modes tests cannot exercise (concurrency,
  numerical, adversarial input, partial failure) are reasoned about explicitly, and the reasoning
  appears in the PR.
- **No available criticism.** Read the diff as a hostile staff engineer would and answer every
  objection *before* delivery. If you can name a criticism, so can they: fix it.
- **Scalable.** State the complexity of what you added and the input size it holds to. A path
  that degrades on real data is a defect, not a trade-off, unless the limit is measured and
  stated.
- **Secure.** Untrusted input validated at the boundary, no injection surface, no secret in code
  or log, no permission silently widened. Auth, crypto, billing and data-integrity paths get the
  full treatment.
- **Verified.** Every claim carries evidence a reader can re-run: the command and its output, the
  measurement, the before and after.

**Anything below this is denied on the spot, by you, before it reaches the user.** You are the
first reviewer and the strict one. A delivery you would not defend line by line in front of the
best engineer you can imagine does not leave the loop.

## Review: Claude Code's native commands, one cycle

The review is Claude Code's own, not one written for this loop: `/code-review` for correctness
and `/security-review` for security. Run each once on the diff, apply what they report, and the
review is over. There is no home-made review procedure, no verdict format, no re-review, no
second round, no change-request loop and no iterating until approval.

Quality comes upstream, while the code is written, not from a longer review.

## Every modification is governed by a genius pattern

Delegated work runs on a Claude Code built-in subagent (`general-purpose`, `Explore` or `Plan`).
That agent MUST apply the reasoning pattern of one or two genius agents chosen for the task.
The delegation prompt carries one line, `GENIUS: <name>[, <name>]`, naming files in
`agents/genius/<name>.md`, and embeds or points to the method in that file. The task-class to
built-in type to genius mapping is `rules/agent-routes.json` (rendered in
`rules/agent-routing-table.md`). The PreToolUse hook `hooks/pre-agent-genius-gate.py` denies an
Agent call that lacks the line, names an unknown genius, or targets a removed team-role agent
type.

Every modification is therefore governed by principles those geniuses already established, and
the code must respect the published method the pattern carries: the source is read first, the
implementation is derived from it, and the citation is in the code or the PR (the source
precedes the implementation, never the reverse). That is what makes the code meet the science,
and it is what the implementation step below is held to.

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

Apply the genius pattern(s) of the task's `GENIUS:` line while writing, not afterwards: derive
each constant, threshold and algorithm from the published method that pattern carries, read
first, and cite it where the value lives.

### 5. Verify — run the check from step 0

Run it. Read the result. Iterate until it passes.

Report **evidence, not assertion**: the command run and what it returned. If tests fail, say so
with the output. If a step was skipped, say that. "It works" is not a result.

### 6. Benchmark — when a measurable exists

If the repo has a benchmark, run it before and after and record the delta with the exact change
that caused it. A change with no measured delta does not ship as an improvement.

Never tune a rule against the sample used to measure it. If a fix was made because a
measurement exposed it, rebuild the measurement on fresh, held-out data.

### 7. Review: the native commands, once

Run `/code-review` on the diff, then `/security-review`. One run each, one cycle: apply their
findings and the review is over. No home-made reviewer prompt, no verdict comment, no second
round.

Note the model-specific rule (`~/.claude/reference/model-behavior.md`): on Opus 5, do **not** spawn
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

There is one: **the feature is built and functional in the ecosystem**, delivered to standard,
with the evidence in the feature file. Nothing else ends the loop.

Not a partial feature. Not a design proposal. Not a question about what was meant. Not "the code
is written, integration is next". Not a green PR that nothing calls. If the work does not fit in
one pass, checkpoint at `/memories/zetetic-loop/<slug>.md` and continue on the next tick — the
loop resumes where it stopped, and it keeps resuming until the feature runs.

The single exception is a credential, an access, or an authority only the user holds — something
no amount of work on your side can produce. Ambiguity is not one of these: you resolve it from
the code and state what you chose.

## Contract violations — answers that are never acceptable

These are refusals, not preferences. An agent that produces one has broken the contract, and the
owner should not have to say so again.

1. **"Pre-existing" / "outside the blast radius" / "I filed an issue for it" — one refusal
   wearing three faces.** There is no blast radius for breakage, and filing is not an action.
   You touch something and it breaks, you fix it on the way: no discussion, no scoping debate, no
   matter who broke it or when. A red test, a failing check, a violated invariant in code you
   passed through is yours the moment you saw it. **You do not open issues; the user is the only
   one who does.** An issue you file is a way of choosing not to work. Anything you genuinely
   cannot fix goes into the report to the user, who decides.
2. **A skip is a violation.** "Out of scope for this PR", "deferred to a follow-up", "too large
   for one session" — none of these end a task. Work that does not fit is CHECKPOINTED and
   CONTINUED.
3. **A failing PR is a violation.** Red CI is not "done pending checks". **A delegated contract
   ends when it is fulfilled, not when a report is written**: green, mergeable, verified. Until
   then you keep working, do not negotiate the scope down, and do not hand back a red deliverable
   with an explanation attached.

**A contract ends when the root cause is corrected and the refactoring it requires is done.** Not
when the symptom stops showing. Structure the fix exposes — a file past its size cap, a tangled
responsibility, a seam in the wrong place — belongs to the same contract.

**Refusal is not one of the options.** No engineering organisation lets a developer decline the
work. Difficulty and delicacy are reasons to proceed carefully, never reasons to hand it back.

**A shortcut past the engineering fundamentals is refused by default.** SOLID, Clean
Architecture, DRY, separation of concerns, the size limits, root-cause over symptom. Code that
reaches green by duplication, a god function, a layer violation, or an abstraction nothing can
substitute into is refused whether or not its tests pass. Green tests are necessary, never
sufficient.

**A declared violation is still a violation.** Naming a broken rule in the PR body does not
license it. "Declared, not hidden" is a confession, not an acceptance criterion. The fix lands in
the same PR, before delivery, and a regression is fixed, never accepted and never annotated.

**No artefact, no figure, applied in both directions.** A published number carries a committed
artefact that produces it: the run record, the commit it ran at, the dirty flag, the condition.
Enforcing that against the value you remove while the replacement rests on nothing is laundering,
not rigour. When nothing supports any candidate, publish "no traceable figure" and own it. And
**absence of a field is not absence of provenance** — campaigns store it per row, per directory,
or in a sibling manifest, so resolve the commit before calling a number untraceable.

**Enforce all of this on anything you delegate**, and remember that **an agent's final report is
not proof that it stopped**: check the process list, not the report, before calling a tree clean
or a measurement valid.

Corollary: **finish what you open.** An abandoned branch, or a green PR left unmerged with no
owner, is the same failure as leaving CI red.

## What this loop refuses

Code produced directly from a prompt. Work reported as done without evidence. A merged change
that is unreachable from the production path — test-gated, flagged off, uncalled — presented as
progress. A benchmark tuned until it agrees. A negative claim asserted from an incomplete
search.

$ARGUMENTS
