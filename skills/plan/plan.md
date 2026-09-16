---
name: plan
description: >
  Turn an active goal contract into an ordered plan where every step carries its own check,
  then verify the plan against the goal before any code is written: each criterion is
  covered by at least one step, no step touches a non-goal, and the first step is the one
  that retires the most uncertainty.
category: loop
trigger: >
  After a goal file reaches status active and before the first implementation step; again
  after refine-goal writes a new backlog; whenever a step fails twice in a row for the
  same reason.
agents:
  - architect
  - engineer
shapes: []
input: >
  The path of an active goal file (default: the only active file under .zetetic/goals/).
output: >
  The Plan section of the goal file: ordered steps, each with its check, the criteria it
  serves, and the verify-plan verdict.
zetetic_gate:
  logical: "Every acceptance criterion maps to at least one step; every step maps to at least one criterion"
  critical: "The plan is judged against the goal file as written, never against the request as remembered"
  rational: "Steps are ordered by uncertainty retired, not by ease; the risky step comes first"
  essential: "A step whose removal changes no criterion is deleted"
composes: []
aliases: [plan-goal, verify-plan]
portable:
  package: zetetic-loop
hand_off:
  plan_unsound: "rewrite the plan with the verify-plan findings as input; no code yet"
  plan_sound: "execute the first step, then verify-goal"
---

## Purpose

A plan written from memory of the request drifts from the contract. This skill writes the
plan from the goal file and checks it against the same file, so the work that follows is
judged by criteria that existed before the plan did. The host's native plan mode, when one
exists, is a fine place to draft; the goal file is where the plan is kept.

## Procedure

1. **Read the goal file.** Refuse to plan a goal whose status is not `active`, or whose
   criteria table is empty.
2. **Read the code the criteria touch.** Open every file a criterion's command reads or a
   step will change. Never plan a change to code that has not been opened.
3. **Draft the steps.** Each step states: what changes, in which files, which criteria it
   serves, and the check that proves the step is done (a command, or a reviewer reading a
   named artifact). A step with no check is split until each part has one.
4. **Order by uncertainty.** Put first the step most likely to show the goal is impossible or
   mis-specified. A cheap step that could invalidate the whole plan runs before an expensive
   step that assumes the plan holds.
5. **Verify the plan** against the goal file:
   - coverage: every criterion id appears in at least one step; list any orphan criterion;
   - scope: no step writes inside a non-goal; list any violation;
   - order: the first step retires more uncertainty than the second; state why;
   - budget: the step count fits the iteration budget, or the plan says which steps merge.
   Record the verdict `sound` or `unsound` with the findings.
6. **Write the Plan section** of the goal file: the steps, the mapping, the verdict. Replace
   the previous Plan section; keep its verdict line in the Iterations ledger.
7. **Stop** when the verdict is unsound. Rewrite with the findings as input. Do not execute
   an unsound plan to "see what happens".

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | criteria and steps map both ways | add the missing step or delete the orphan |
| Critical | plan judged against the file, not the memory of the request | re-read the file, re-verify |
| Rational | riskiest step first | reorder and state the reason |
| Essential | every step changes a criterion's outcome | delete the step |

## Output Format

```markdown
## Plan
verify-plan: sound | unsound (<date>)
| step | change | files | serves | check |
|------|--------|-------|--------|-------|
| S1 | <what> | <paths> | C1, C3 | `<command>` exits 0 |
findings: <coverage / scope / order / budget notes, or "none">
```

## Hand-offs

| Condition | Next skill | Reason |
|-----------|------------|--------|
| verdict sound | execute S1, then verify-goal | the plan is covered and in scope |
| verdict unsound | plan (again) | findings become the input |
| a criterion cannot be served by any step | goal | the contract, not the plan, is wrong |

## Anti-patterns

- Planning from the chat history instead of the goal file.
- A step called "implement the feature" with no files and no check.
- Ordering by convenience so the hard step is discovered last.
- Silently dropping a criterion the plan cannot serve.

## Examples

Goal with C1 `pytest tests/auth` exits 0 and C2 fixtures unchanged. Plan: S1 run the suite
and record the failing tests (serves C1, check: the failure list is in the transcript); S2
fix the token expiry path in `auth/session.py` (serves C1, check: the two named tests pass);
S3 `git diff --stat main -- tests/auth/fixtures` is empty (serves C2). Verdict sound; S1 first
because it may show the failures are in fixtures, which would make the goal impossible.
