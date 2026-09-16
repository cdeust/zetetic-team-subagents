---
name: refine-goal
description: >
  After a verify-goal run, turn the ledger into the next iteration: tighten criteria that
  passed by accident, add the criterion a failure revealed was missing, write the backlog
  the next plan starts from, and record the lesson in the memory layer. Never widens the
  end state; a wider end state is a new goal.
category: loop
trigger: >
  After every verify-goal entry with status active; after a goal reaches met, once, to
  harden the criteria before the goal is reused as a template; when two iterations refute
  each other without converging.
agents:
  - code-reviewer
shapes: []
input: >
  The path of a goal file whose latest iteration was written by verify-goal.
output: >
  A refine entry in the Iterations section (backlog, criteria changes, lesson), the
  updated criteria table, and a memory-layer entry for each lesson.
zetetic_gate:
  logical: "Every backlog item traces to an unmet row or to a criterion change made here"
  critical: "A criterion is tightened only with the evidence that showed it was loose"
  rational: "Refinement narrows; anything that would widen the end state is refused and handed to the goal skill"
  essential: "A lesson is recorded only if a future session would act differently for knowing it"
composes: [refine]
aliases: [refine-iteration, post-verify-refine]
portable:
  package: zetetic-loop
hand_off:
  backlog_written: "plan, with the backlog as its input"
  oscillation: "two iterations undo each other; stop and hand the goal to the user with both ledgers"
  scope_pressure: "the only way to pass would widen the end state; hand to goal for a new contract"
---

## Purpose

An iteration that only fixes what failed converges slowly and forgets what it learned. This
skill reads the evidence the last verification produced and rewrites the contract's edges,
never its centre: criteria get sharper, the backlog gets concrete, the lesson gets stored.
The pre-execution refine procedure binds a vague request to artifacts; this skill binds a
measured result to the next attempt.

## Procedure

1. **Read the latest verify-goal entry.** Refuse when the latest entry is not a verify-goal
   entry, or when status is `blocked` (a broken check is fixed by the goal skill, not here).
2. **For each unmet row**, write one backlog item: the criterion id, what the evidence showed,
   the smallest change that would flip the verdict, and the files it touches. No item without
   a criterion id.
3. **For each met row**, ask whether it passed for the right reason. A test that passed
   because it was skipped, a diff that was empty because nothing ran, a count that matched
   by coincidence: tighten the check so the accident cannot recur, and quote the evidence
   that justified the tightening.
4. **Look for the missing criterion.** A failure that the criteria did not predict means the
   contract has a gap. Add the criterion with its command. State that it is new so the next
   verify-goal run reports it separately.
5. **Refuse widening.** If the only way to a met verdict is to change the end state or a
   non-goal, stop and hand off to the goal skill; write why in the entry.
6. **Detect oscillation.** If this backlog reverses the previous one, stop and report both
   entries to the user instead of iterating.
7. **Write the refine entry** (format below) and update the criteria table in place.
8. **Record the lesson** in the memory layer, tagged as archival with the goal slug as topic,
   only when a future session would act differently for knowing it. Session state is not a
   lesson.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | each backlog item names a criterion id | drop the item |
| Critical | each tightening quotes its evidence | revert the tightening |
| Rational | the end state is unchanged | hand off to goal |
| Essential | lessons change future behaviour | do not store |

## Output Format

```markdown
### Iteration <n> (<date>) by refine-goal
backlog:
- C2: fixture `tests/auth/fixtures/users.json` was rewritten by S2; restore it and move the
  new user to a test-local factory (`tests/auth/test_session.py`).
criteria changes:
- C1 tightened: `pytest tests/auth -p no:cacheprovider --strict-markers` (evidence: 3 tests
  were skipped in iteration 2 and counted as passed).
- C4 added: `pytest tests/auth -rs | grep -c SKIPPED` prints 0.
lesson: fixtures are shared state; a criterion on a suite needs a criterion on its skips.
```

## Hand-offs

| Condition | Next skill | Reason |
|-----------|------------|--------|
| backlog written | plan | the next iteration starts from the backlog |
| widening needed | goal | a new contract, not a refinement |
| oscillation | user | the loop is not converging |

## Anti-patterns

- Relaxing a criterion so the last result counts as met.
- A backlog item that says "fix the remaining issues".
- Storing the iteration ledger as a lesson.
- Continuing after two reversals because the budget is not yet spent.

## Examples

Iteration 2 left C2 unmet and C1 met with three skipped tests. Refine entry: one backlog item
for C2, C1 tightened with strict markers, C4 added for skips, lesson stored. Plan runs next
with that backlog; verify-goal in iteration 3 reports C4 as new.
