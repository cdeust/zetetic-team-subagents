# Advisor and goal-loop composition

Request: "The only missing part after the goal-loop would be the cumulation with the advisor-model loop and advisor-model skill. But this should be a separate PR"
Clarification: "same principle as advisor command in claude code"

Bindings: goal-loop is PR #141 at 2b8dd12; advisor is the native Claude Code
`/advisor` behavior documented at https://code.claude.com/docs/en/advisor
(read 2026-09-17). The existing `agents/advisor.md` is a possible delegated
implementation, not the native server tool.

Goal: provide a portable advisor-model skill and an advisor loop that compose with
the goal contract while preserving executor ownership and external acceptance.
The missing behavior is consultation within the existing goal cycle.
Host configuration changes and claims of measured cost savings are excluded.

Strategy: write the state transitions first, then validate packaging and exercise
the instructions against external checks in isolated operator scenarios.

- [x] Bind the user's reference to the native command documentation.
- [x] Create an isolated branch from the reviewed goal-loop head.
- [x] Implement portable skill, command and goal-loop integration.
- [x] Check package discovery, body parity and documentation counts.
- [x] Forward-test advice acceptance, contradictory evidence and finite budgets.
- [x] Review the final diff and run applicable gates.
- [x] Publish separate PR #142. Remote CI and the review verdict are recorded on the PR.

## Review

Full suite: 40 passed, 0 failed (`tests/run-all.sh`, explicit repository venv
Python). Final package tests: 46 passed after allowing public citation URLs in
the runtime-word scan. Skill metadata validation and body parity passed.
Documentation counts: 37 claims, zero problems. Staged source and craftsmanship
gates reported zero errors or warnings; strict prose scan passed.

Independent review found and corrected two transitions: a criterion proposal now
runs verification before refinement, and a required declined advisor blocks the
goal. The reviewer approved both corrected paths.

Operator scenarios use simulated responses and usage, plus real Python acceptance
checks in `/private/tmp/advisor-forward`. They establish behavior in the supplied
scenarios; they do not establish native server-tool invocation or cost savings.

Final operator pass: 10 fixture state checks and 5 independent executable checks
passed. Source hashes were stable across that run. Required decline and pre-plan
criterion tightening were included. PR #141 merged as db5f697; PR #142 contains only the advisor composition.
