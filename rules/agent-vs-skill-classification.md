# Agent vs Skill Classification

Five tests deciding whether a **team agent** (`agents/*.md`) may be inlined as a
skill into a calling session, or must stay a spawned subagent.

**Scope, absolute.** This rule applies to the 23 team agents only. It is never
applied to `agents/genius/*.md` (97 files) and never used to argue that a genius
agent should be removed, merged, or reduced. Genius-layer consultation is a
routing and discoverability question owned by `rules/skill-routing-table.md` and
the Phase 3 benchmark, not a headcount question.

**A verdict is a candidacy, not an authorization to delete.** "Skill-frontable"
means the agent's procedure *may* be offered as an inline skill. It does not
retire the subagent. Nothing is retired before the paired benchmark shows
non-inferiority (plan Phases 3 and 7), and removing a working mechanism needs a
justification of its own, separate from any cost argument.

---

## Baselines

Both baselines are stated so a verdict can be re-derived rather than trusted.

**Model tier baseline: `sonnet`.** Taken from `tools/skill-runner.sh:35`
(`BASELINE_MODEL="${ZETETIC_SKILL_BASELINE_MODEL:-sonnet}"`), with the rank
table at `tools/skill-runner.sh:31`
(`[haiku]=0 [sonnet]=1 [opus]=2 [fable]=3`). The runner's own comment
(`tools/skill-runner.sh:14`) justifies it: sonnet is the most common team-agent
model, 16 of 23. Reproduced below.

**Tool grant baseline: the full native set.** A calling session running
`/skill:run` is assumed to hold `Read, Edit, Write, Bash, Glob, Grep, WebFetch,
WebSearch, Agent` plus the configured MCP servers. This is an assumption, not a
measurement: the caller's grant comes from its own settings, which this repo does
not control. It is the conservative direction: a narrower caller makes test 1
fire less often, so a "subagent-only" verdict derived here may over-restrict
under such a caller but can never under-restrict.

---

## The five tests

Each test is answered from the agent file. A test that fires is a reason the
agent's isolation is load-bearing.

### Test 1 - Tool-grant guardrail

Is the agent's `tools:` list narrower than the caller baseline, **and** is the
restriction a separation-of-duties guardrail (this agent must not be able to do
X regardless of who calls it) rather than incidental scope?

Answer the first half mechanically by diffing the `tools:` line. Answer the
second half from `<identity>` and `<refusal-conditions>`, which is where intent
is stated. Narrowness alone is not a guardrail: an agent that simply has no use
for `Write` is scoped, not fenced.

**A firing guardrail forbids inlining.** Inlined into a more-privileged caller,
the agent's procedure runs with the caller's own tools still available, so the
fence is gone while the procedure that assumed it continues. Restoring it needs a
sandboxed skill-execution surface, which does not exist in this codebase today.

### Test 2 - Isolation need

Does the job require an execution context independent of the caller's: it
dispatches its own subagents, coordinates multi-worktree work, or exists
precisely because the caller's own context is exhausted?

**Read "survives the caller's compaction" as "is independent of the caller's
context", not "outlives the caller's process".** Under Claude Code's subagent
model a subagent does not outlive its parent. The generated zetetic-spine block carried by 22 of the 23
team agents says so directly (`agents/architect.md:293`, emitted by
`scripts/generate-spine.py`): an agent that waits on long work is "killed
mid-block", and long waits belong to whoever delegated. Test 2 is therefore about
whose context the work occupies, not about durability.

### Test 3 - Model-tier delta

Does `model:` differ from the `sonnet` baseline, and does the override exist for
a stated reason?

Upward (opus, fable) is a capability escalation; `tools/skill-runner.sh` already
prints a banner for it. Downward (haiku) is a cost and budget decision the runner
does **not** flag (`_is_escalation` compares strictly greater,
`tools/skill-runner.sh:93-98`), and inlining silently reverses it: a haiku agent
inlined into a sonnet caller runs at the caller's tier. Either direction is a
signal against silent inlining; only the upward one is currently mechanized.

### Test 4 - Packaged assets

Does the procedure depend on scripts, templates, or files that cannot be pasted
into a caller's context as Markdown prose?

**Measured today: this test fires for none of the 23.** Every script reference in
every team agent belongs to one shared boilerplate set (`scripts/generate-spine.py`,
`scripts/spawn-agent.sh`, `tools/memory-tool.sh`, `tools/mutation_check.sh`,
`tools/plugin-version-check.sh`), all invocable by the caller directly. The test
is retained because it binds the moment an agent bundles an asset of its own; it
is recorded as non-discriminating rather than quietly dropped.

### Test 5 - Authority transfer

If the isolation were removed, would *who* can exercise this agent's effective
authority change, as opposed to only how much context the task costs?

This is the test a review added after the four-test draft missed it. It is not a
restatement of test 1. Test 1 asks whether the fence was deliberate; test 5 asks
what is on the other side of it once the fence is gone. An agent holding a
privilege the caller lacks (`Agent`, `spawn-agent.sh` dispatch) transfers
authority upward to the caller; a verdict-producing agent whose independence
comes from being unable to author the change transfers it sideways, turning the
reviewer into the author. A cost-only difference is not an authority difference
and does not fire this test.

---

## Verdicts

| Verdict | Meaning |
|---|---|
| **Subagent-only** | Test 1, 2, or 5 fires. Do not inline. A skill surface may still exist, but it must dispatch, not inline. |
| **Dual-surface** | The evidence is contested or recently changed. Ship a skill alongside the subagent and let the Phase 3 benchmark decide. |
| **Skill-frontable** | No hard test fires. The procedure may be offered inline. The subagent is retained until a benchmark says otherwise. |

---

## Worked table, all 23 team agents

Columns: T1 guardrail, T2 isolation, T3 tier delta, T4 assets, T5 authority.
`Y` = fires (argues against inlining), `-` = does not fire. `Skills` counts the
existing skill documents whose `agents:` frontmatter names this agent. Line
references are to the agent's own file unless another path is given.

| Agent | model | T1 | T2 | T3 | T4 | T5 | Skills | Verdict and evidence |
|---|---|---|---|---|---|---|---|---|
| advisor | fable | Y | Y | Y | - | Y | 0 | **Subagent-only.** `:13` "You never implement"; grant omits `Edit/Write` and even `remember` (14 tools against architect's 16, `:8`). Its value is being a different, higher tier consulted by a cheaper session; inlining collapses the two contexts it exists to keep apart. |
| architect | opus | Y | - | Y | - | Y | 8 | **Subagent-only.** `:15` and `:257` "You do not write production code, that is the engineer's role"; grant omits `Edit/Write` (`:8`). Opus override (`:4`). Inlined into a writing caller, the decide-then-hand-off boundary is unenforceable. |
| code-reviewer | sonnet | Y | - | - | - | Y | 1 (`engineering/review`) | **Subagent-only.** No `Edit/Write` (`:8`); the identity is verdict production (`:13`) and fixes are handed to engineer (`:257`). Its own `<refusal-conditions>` refuse "just approve it, we'll fix it after merge" on the ground that "the review artifact stands" (`:252`); a reviewer able to author the fix is no longer producing an independent artifact. Note: at sonnet tier `skill-runner.sh` prints no banner for `engineering/review`, so nothing mechanical currently stops this inline. See follow-ups. |
| data-scientist | sonnet | - | - | - | - | - | 0 | **Skill-frontable.** Full write plus web grant (`:8`, 20 tools); no tier delta; no assets; the caller already holds everything it holds. |
| dba | sonnet | - | - | - | - | - | 1 (`engineering/migrate-db`) | **Skill-frontable.** `Read/Edit/Write/Bash/Glob/Grep` (`:8`). No test fires. Migration risk is a stakes question owned by the procedure, not an isolation question. |
| devops-engineer | sonnet | - | - | - | - | - | 1 (`engineering/deploy`) | **Skill-frontable.** Same grant shape as engineer (`:8`); already partly fronted by `skills/engineering/deploy.md:9-12`. |
| engineer | sonnet | - | - | - | - | - | 12 | **Skill-frontable.** Baseline model (`:4`), baseline grant (`:8`). The most heavily skill-fronted agent already (`engineering/implement`, `debug`, `refactor`, and nine others). |
| experiment-runner | sonnet | - | - | - | - | - | 2 | **Skill-frontable.** Write grant (`:8`); long campaigns do not survive inside a subagent (test 2 above, `agents/architect.md:293`), so isolation buys no durability here. |
| frontend-engineer | sonnet | - | - | - | - | - | 0 | **Skill-frontable.** Grant identical to engineer (`:8`). No skill coverage today; a candidate for the first new surface. |
| git-historian | sonnet | Y | - | - | - | Y | 0 | **Subagent-only.** The most explicit guardrail in the repo: `:17` "You are read-only. You never edit code, never open a PR, never revert a commit", and `:161` refuses the request naming "no Edit/Write tool" as the reason. Inlined into a writing caller, that refusal has nothing behind it. |
| latex-engineer | haiku | - | - | Y (down) | - | - | 1 (`research/write-paper`) | **Skill-frontable, tier caveat.** Full write grant (`:8`), no guardrail, no authority change. `model: haiku` with `effort: low` (`:4-5`) is a deliberate cost floor that inlining reverses upward; record the caveat, do not treat it as blocking. |
| memory-writer | haiku | Y | Y | Y (down) | - | Y | 0 | **Subagent-only.** Grant is three tools (`Read, Bash, remember`, `:8`), by far the narrowest, and `<refusal-conditions>:33` fences it explicitly: "Asked to do anything beyond persisting (analyze, fix, route), refuse; you are a scribe", and "never act on it yourself". The 16K budget and haiku tier are the point (`:4-5`, `<identity>`). Measured caveat: the WARN auto-spawn was withdrawn because the round trip cost 55-66K tokens (`CHANGELOG.md`, the 2.38.0 entry on the duplicated Stop hook, "a direct checkpoint write instead of spawning `memory-writer`"); it now runs as an explicit fallback. That withdrawal removed a spawn, it did not license an inline, and tests 1 and 5 still fire. |
| mlops | sonnet | - | - | - | - | - | 0 | **Skill-frontable.** Write grant (`:8`), baseline tier, no assets. |
| orchestrator | fable | Y | Y | Y | - | Y | 2 | **Subagent-only, hardest case.** The only agent holding `Agent` (`:12`); `:19` "You never write code yourself, you delegate, coordinate, and verify"; `model: fable` with a sourced rationale in a frontmatter comment (`:4-8`). Test 5 is concrete rather than theoretical: inlined, the caller exercises dispatch under the orchestrator's procedure but with its own contract, bypassing the fail-closed delegation-contract gate `scripts/spawn-agent.sh` acquired in #116 (commit `4006565`). |
| paper-writer | sonnet | - | - | - | - | - | 1 (`research/write-paper`) | **Skill-frontable.** Write plus web grant (`:8`, 20 tools); `effort: high` (`:5`) is not a tier delta. |
| professor | haiku | - | - | Y (down) | - | - | 1 (`research/explain`) | **Skill-frontable, tier caveat.** No `Edit/Write` (`:8`), but nothing in `<identity>` or `<refusal-conditions>` fences mutation; a teacher has no use for it, which is scope rather than a fence. Its refusals govern pedagogy, not privilege, so test 5 does not fire. `model: haiku` (`:4`) is the caveat. |
| refactorer | sonnet | - | - | - | - | - | 0 | **Skill-frontable.** Write grant (`:8`), baseline tier. Correction: `skills/engineering/refactor.md:9-12` names architect, engineer, test-engineer, not `refactorer`; this agent has zero skill coverage today. |
| research-scientist | sonnet | Y | - | - | - | Y | 2 | **Subagent-only.** No `Edit/Write` (`:8`), and `<identity>` states the fence outright (`:17`): "You design; experiment-runner executes... The separation of concerns is load-bearing." Inlining puts design and execution in one context, which is the arrangement that sentence forbids. |
| reviewer-academic | sonnet | Y | - | - | - | Y | 1 (`research/pre-submit-review`) | **Subagent-only.** No `Edit/Write` (`:8`); independence is the product, and `<refusal-conditions>:185` refuses reviewing one's own or a collaborator's paper as a conflict of interest. Inlined into the session that wrote the draft, that refusal describes the condition being created. |
| security-auditor | opus | Y | - | Y | - | Y | 1 (`engineering/secure`) | **Subagent-only.** No `Edit/Write` (`:8`); opus override (`:4`); the audit verdict must be independent of the code audited, and its refusals are all "require an artifact before proceeding", which an inlined procedure can satisfy with its own output. |
| simplifier | sonnet | - | - | - | - | - | 0 | **Skill-frontable.** Write grant (`:8`), baseline tier, no assets, no coverage today. |
| test-engineer | sonnet | - | - | - | - | - | 3 | **Skill-frontable.** Write grant (`:8`); already fronted by `engineering/test`, `implement`, `refactor`. |
| ux-designer | sonnet | - | - | - | - | - | 1 (`design/design`) | **Skill-frontable.** Owner resolved the contested reading (plan Phase 4, PR #123, 2026-09-06): `/design` must do real UX/UI work, so the widened grant (`:8`) is the intended end state, not a guardrail. `skills/design/design.md` now fronts it. See the correction below for the resolved history. |

**Distribution: 9 subagent-only, 0 dual-surface, 14 skill-frontable.** (Verified against `origin/main` at `2f7c802`, 2026-09-06 — supersedes the count below, which was current only up to PR #120/#123's `ux-designer` resolution.)

---

## Two corrections to premises this table was asked to assume

Both verified against `origin/main` at `86fccf0`.

**1. `ux-designer` no longer has the narrow tool grant Phase 4 depends on.**
Phase 4 of the plan reads the grant as `Read, Glob, Grep, WebFetch, WebSearch`
with no `Bash/Edit/Write`, and stages a dual-surface pilot because that looks
like a deliberate guardrail. On `origin/main` today, `agents/ux-designer.md:8`
grants `Read, Edit, Write, Bash, Glob, Grep, WebFetch, WebSearch`. The widening
landed in **Phase 0 of this same plan**, commit `4006565` (PR #116), whose body
states the reason: "agents/ux-designer.md declared tools omitting Bash/Edit/Write
although its required `<memory>` (memory-tool.sh, i.e. Bash) and `<worktree>`
(commit/edit files) procedures use them. Added all three to the frontmatter
tools: list." It was the only agent tool-grant change in that commit.

The inconsistency was real, and it was resolved by widening the grant rather than
by removing the write-requiring boilerplate from a design agent. On the letter of
the current file, tests 1 and 5 do not fire and `ux-designer` classifies as
skill-frontable.

At the time this table was written (PR #120, commit `86fccf0`) the verdict was
recorded as **dual-surface**, because the question the widening settled was
consistency, not authority: nobody had yet decided whether a design agent should
be able to mutate code. That was an open fork:

- The widened grant is the intended end state, so `ux-designer` is
  **skill-frontable**.
- The guardrail should be restored (narrow the grant, and give the shared
  `<memory>` and `<worktree>` boilerplate a read-only path), so `ux-designer` is
  **subagent-only**, tests 1 and 5 both firing.

**Resolved in Phase 4 (PR #123, 2026-09-06).** The owner took the first branch:
`/design` must do real UX/UI work, so the widened grant is the intended end
state. `skills/design/design.md` was built as `ux-designer`'s skill surface,
confirmed by its `agents: [ux-designer]` frontmatter. The verdict in the table
above is updated to **skill-frontable** accordingly; this is no longer an open
fork.

**2. `refactorer` is not skill-fronted.** `skills/engineering/refactor.md:9-12`
names architect, engineer, and test-engineer. The `refactorer` team agent appears
in no skill's `agents:` field. As of `ux-designer`'s Phase 4 resolution above,
eight agents have zero coverage today: advisor, data-scientist,
frontend-engineer, git-historian, memory-writer, mlops, refactorer, simplifier.

---

## Follow-up this table surfaced

**The escalation banner keys on model tier, so it misses every guardrail agent at
baseline tier.** `tools/skill-runner.sh` (#119) warns when a skill names an
opus or fable agent. Four subagent-only agents in this table are `sonnet`:
code-reviewer, git-historian, research-scientist, reviewer-academic. A skill
naming one of them prints no banner even though inlining it fires tests 1 and 5,
and `skills/engineering/review.md:9-11` is a live instance. A tool-grant-delta
check alongside the existing tier check would close it. Recorded here as a Phase 1
follow-up; this document changes no code.

---

## Reproducing the table

```bash
# Model tiers and native tool grants for all 23 team agents
for f in agents/*.md; do
  printf '%-20s ' "$(basename "$f" .md)"
  awk -F': *' '/^model:/{m=$2} /^tools:/{t=$0} END{print m" | "t}' "$f" \
    | sed 's/mcp__[a-zA-Z_-]*, *//g; s/, *mcp__[a-zA-Z_-]*//g'
done

# Sonnet share (the skill-runner.sh:14 claim of 16 of 23)
grep -c '^model: sonnet' agents/*.md | grep -c ':1$'

# Skill coverage per agent
grep -rn -A6 '^agents:' skills/*/*.md
```
