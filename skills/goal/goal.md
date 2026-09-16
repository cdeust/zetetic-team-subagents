---
name: goal
description: >
  Compile a long-running objective into a persistent, host-neutral goal contract: one
  measurable end state, non-goals, acceptance criteria written as external checks with an
  expected exit code, a budget, and an iteration ledger. Mirrors the end state into the
  host's native goal command so the host's stop check and the contract agree.
category: loop
trigger: >
  Before any multi-turn or multi-session task that must converge on a verifiable end state;
  when a request says "until it passes", "keep going until", "iterate until green"; when a
  native goal would carry only a sentence and the work needs criteria that survive a
  context reset or a change of host.
agents:
  - engineer
shapes: []
input: >
  A request in prose, or the path of a file describing one. Optional slug and budget.
output: >
  A goal file at .zetetic/goals/<slug>.md with status draft or active, plus the one-line
  condition handed to the host's native goal command.
zetetic_gate:
  logical: "Every criterion is a command with an expected result; a criterion the transcript cannot demonstrate is rewritten or dropped"
  critical: "The end state is stated so that a fresh evaluator reading only the transcript can decide met or not met"
  rational: "One goal, one end state; a request with two independent end states becomes two goal files"
  essential: "Non-goals are written down so later iterations cannot widen the contract silently"
composes: [refine]
aliases: [set-goal, goal-contract]
portable:
  package: zetetic-loop
hand_off:
  no_check_nameable: "the request is not ready; return to scoping, do not activate the goal"
  planning: "plan reads the active goal and writes the ordered steps"
---

## Purpose

A native goal command stores one sentence and asks a small model to judge it from the
transcript after each turn. That is enough to keep a session running and not enough to keep
the work honest: the sentence carries no acceptance commands, no non-goals, no budget, and it
does not survive a change of host. This skill writes the contract the sentence stands for,
in a file both hosts and every later session can read, and then hands the host the sentence.

## Procedure

1. **Bind the request.** Resolve every named system, file, or concept to a concrete artifact
   with evidence (grep, git history, the memory layer's recall). When the wording is vague,
   run the refine procedure first. Do not guess a binding silently.
2. **Name the end state.** One sentence, one measurable condition: a test result, a build
   exit code, a file count, an empty queue. If two independent end states are present, write
   two goals.
3. **Name the check for each criterion.** Each acceptance criterion is a row with an id, the
   criterion in prose, the exact command that proves it, the expected result (exit code or
   output pattern), and its kind: `deterministic` when a command decides, `review` when a
   reader must judge. A criterion with no command and no reader is not a criterion.
4. **Write the non-goals.** What this goal will not change, so that a later iteration cannot
   widen the scope to make a criterion pass.
5. **Set the budget.** Maximum iterations and, when the host reports it, a token ceiling.
   A goal with no budget runs until the user stops it; say so explicitly if that is intended.
6. **Write the file** at `.zetetic/goals/<slug>.md` using the format below, status `active`.
   If no check could be named in step 3, leave status `draft` and stop: the request is not
   ready to run.
7. **Mirror into the host.** Hand the host's native goal command a condition of the form:
   `verify-goal reports every criterion of .zetetic/goals/<slug>.md met, with the command
   output in the transcript, or the iteration budget of N is spent`. The native evaluator
   reads only the transcript, so the condition must name what the transcript will show.
8. **Record the decision** in the memory layer: the slug, the end state, and the reason for
   each non-goal.

## Goal file format

```markdown
---
slug: <slug>
status: draft | active | met | blocked | exhausted
created: YYYY-MM-DD
budget:
  iterations: <N>
  tokens: <N or null>
---
# Goal: <one-sentence end state>

## Non-goals
- <what stays untouched, and why>

## Acceptance criteria
| id | criterion | check | expected | kind |
|----|-----------|-------|----------|------|
| C1 | <prose> | `<command>` | exit 0 | deterministic |
| C2 | <prose> | reviewer reads <path> | <what they must find> | review |

## Plan
<written by the plan skill>

## Iterations
<appended by verify-goal and refine-goal, newest last>

## Lessons
<appended by refine-goal>
```

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | every criterion has a command and an expected result | rewrite or drop the criterion |
| Critical | the end state is decidable from the transcript alone | rephrase until a fresh reader can judge it |
| Rational | one end state per goal | split into two goal files |
| Essential | non-goals written before activation | do not set status active |

## Output Format

The goal file path, its status, the condition handed to the host, and the list of criteria
with their kind. Nothing else: planning belongs to the plan skill.

## Hand-offs

| Condition | Next skill | Reason |
|-----------|------------|--------|
| status active | plan | the contract exists; order the work |
| status draft | none | no check could be named; scope with the user |

## Anti-patterns

- A criterion phrased as "works correctly" or "looks good": the transcript cannot show it.
- Setting the native goal without the file: the sentence is lost on the next host.
- Widening the end state during an iteration: that is a new goal, not a refinement.
- Inventing a budget the user did not ask for and hiding that it exists.

## Examples

Request: "make the auth tests pass without touching the fixtures".
End state: `pytest tests/auth` exits 0. Non-goal: `tests/auth/fixtures/` unchanged, checked
by `git diff --stat main -- tests/auth/fixtures` being empty. Two deterministic criteria,
budget five iterations, status active, native condition names both commands.
