# Handoff: genius-only agents (branch chore/genius-only-agents), 2026-10-21

Written at the owner's request before the parent session is cleared. Nothing here is a merged or reviewed result. No PR is open.

## Done

Part A, delete the 23 team-role agents and repair consumers
- `agents/` holds only `agents/genius/` (97 agents plus `INDEX.md`; the owner said 98, the tree has 97 `name:` files).
- Generators: `scripts/generate-spine.py` and `scripts/generate-routing-table.py` iterate genius only; spine and routing table regenerated (`--check` green).
- Routing (spec correction 1): `rules/agent-routes.json` maps 23 task classes to a built-in `subagent_type` plus 1 or 2 genius agents; rendered at the end of `rules/agent-routing-table.md`. No route for `latex-engineer`, `memory-writer`, `orchestrator`, `advisor` (no genius equivalent).
- Hook (spec correction 2): `hooks/pre-agent-genius-gate.py`, registered in `hooks/hooks.json` and `.claude-plugin/plugin.json` (PreToolUse, `Agent|Task`), enforce by default (`ZETETIC_AGENT_GATE=observe|off`). Marker: a line `GENIUS: <name>[, <name>]`. Tests: `tests/test_agent_genius_gate.py` (45), fail-before measured 43 of 45 failing on origin/main.
- Checkpoint (spec correction 3): `hooks/stop-context-guard.py` writes the checkpoint itself via `tools/checkpoint_summary.py`; no block, no subagent. Tests: `tests/test_checkpoint_summary.py` (6) plus the rewritten block in `tests/test_context_guard.py`; fail-before measured 3 of 3 hook tests failing on origin/main.
- Review (spec corrections 4 and the user's later messages): `commands/zetetic/engineering-loop.md` now says the review is the native `/code-review` then `/security-review`, one run each, one cycle; the ZETETIC-REVIEW format, the round budget and the three-violations rule are removed; every modification is governed by the genius pattern named for the task. `skills/engineering/review.md` and `commands/zetetic/review.md` defer to the same two commands.
- Consumers changed: 34 skills (`agents:` now genius), `skills/_index.md`, 15 problem-shaped `SKILL.md` fallbacks, `tools/skill-runner.sh` (+ its test), `tools/agent-catalog.sh`, `tools/cycle_evidence.py`, `scripts/spawn-agent.sh`, `scripts/setup.sh`, `scripts/lib/actions.sh`, `scripts/lib/overrides.sh`, `.claude/workflows/autonomous-build-loop.js`, `rules/coding-standards.md` (+ plugin mirror), `rules/agent-reference/*`, `docs/*`, README/CONTRIBUTING/marketplace counts (`tools/doc-count-check.sh` green: 97 agents, 25 hook registrations, 66 tools), `docs/COUNTING.md`, CHANGELOG (Changed, Added, Removed), 97 genius agents (hand-offs now name Simon/Toulmin/Fisher/Cochrane or a general-purpose delegate; spine regenerated).
- Retired: `rules/agent-vs-skill-classification.md`; two tests of deleted agent files in `tests/test_push_authority_consistency.py`.
- Kept on purpose (history or data): CHANGELOG history, `memory/` scope registry and ADRs, `tools/bench-agent-cost` and `docs/bench-agent-cost` (frozen experiment record), `tasks/`, `docs/verification/`, the `scripts/patch_*.py` one-shot migrations and `scripts/upgrade_agents.py` (documented in `pyproject.toml` as kept records).

## Remaining

1. Re-run `scripts/gate.sh commit` (full pytest) on the head tree. The full pytest gate was GREEN on the previous tree (proof e3d6018bd602167d743562726c155001048145bb); after it, only the craftsmanship refactors below were made (nesting and parameter-count extractions in `hooks/pre-agent-genius-gate.py`, `scripts/generate-routing-table.py`, `tools/checkpoint_summary.py`, two test helpers), re-proven by the scoped suites (138 passed: context_guard, checkpoint_summary, agent_genius_gate) and `craftsmanship-checker --staged` (0 blocking). The branch was pushed without a fresh full-suite proof at the owner's request.
2. Run `bash tests/run-all.sh` once, `bash tools/doc-command-check.sh`, `ZETETIC_PROFILE=strict bash tools/zetetic-checker.sh --staged`.
3. Fresh whole-tree grep for the 23 names (script in the session scratchpad; use `(?<![\w-])name(?![\w-])`). Expected residue only: CHANGELOG, `memory/`, bench record, `tasks/`, `docs/verification/`, `rules/agent-routes.json`, `hooks/pre-agent-genius-gate.py`, the new tests, the patch scripts, plain-English "engineer"/"architect"/"professor"/"advisor" in genius agents.
4. `scripts/gate.sh push`, `git push -u origin chore/genius-only-agents`, `gh pr create` (body: both changes, test counts, three pillars; ends with the Claude Code footer), check remote head equals local, commit evidence `docs/verification/pr-<N>-genius-only-2026-10-21.md`, then `disk_hygiene link-pr`, `evidence-preserved`, `dispose` from the main checkout. Worktree path: `.claude/worktrees/genius-only`, registered with disk_hygiene for session 7650d112-8ae3-4d95-86d2-b05de60b67dc.
5. Not done: the autonomous-build-loop reviewer lenses still use home-made "Approve ONLY if" prompts (outside the owner's named dirs, left as a follow-up).

## Failing tests

- No failing test at this checkpoint. The earlier full-pytest failure, `tests/test_subagent_reflection_gate.py::test_list_command_prints_pending_entries`, asserted the old payload string `engineer`; fixed, and the full pytest gate then passed.
- Craftsmanship pre-commit check (whole-file rule) found 10 violations in files this branch created or touched; all fixed in the head commit (0 blocking now; 10 advisory warnings remain, pre-existing, in `.claude/workflows/autonomous-build-loop.js`).
- Shell suites green: spawn-agent, agent-id-propagation, state-layout, agent-definition-auditor, stop-redaction-gate, setup-plugin-served, skill-model-tier-policy, skill-agent-model-matrix-drift, seed-reviewer-prefs, memory e2e. `tests/run-all.sh` has not been run.

## The four spec corrections and their status

1. Routes target built-in types plus 1 or 2 geniuses, not genius files: done (`rules/agent-routes.json`, routing table, skills, workflow).
2. Mandatory by hook, enforce by default, with tests: done (`hooks/pre-agent-genius-gate.py`, 45 tests). The GENIUS check exempts other plugins' namespaced types and `claude-code-guide`/`statusline-setup`.
3. No memory-writer agent, the hook writes the checkpoint: done in this repo. The live Stop hook is registered by `context-guard@session-optimizer-marketplace`, so that plugin must ship the same `checkpoint_summary.py` approach before the runtime changes. No Cortex remember call (the hook has no non-LLM path to it).
4. Review: native `/code-review` plus `/security-review`, one cycle, no ZETETIC-REVIEW format: done in repo text.

## Out-of-repo changes needed (not edited)

- `~/.claude/agents/dispatch.md`: routes to `zetetic-team-subagents:<team>` and `zetetic-team-subagents:genius:<name>`, both now denied. Change it to pick `subagent_type` from `rules/agent-routes.json` (general-purpose, Explore or Plan) and put `GENIUS: <name>[, <name>]` in the delegated prompt; drop the orchestrator and engineer fallbacks.
- `~/.claude/hooks/merge-gate.py` lines 45, 58, 269-270 and `~/.claude/settings.json` lines 634, 644 parse `ZETETIC-REVIEW: APPROVE` with the head sha; with the format gone `gh pr merge` stays blocked until they check evidence that `/code-review` and `/security-review` ran instead.
- `~/.claude/commands/zetetic/engineering-loop.md` is a stale installed copy (13 Oct); `setup.sh update` refreshes it.
