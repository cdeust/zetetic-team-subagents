---
name: autonomous-build-loop
description: >
  Drive a non-trivial build task to completion through a closed loop: refine the prompt into a
  verifiable acceptance contract, plan, zetetically verify the plan, build with a builder agent (built-in `general-purpose`, GENIUS: dijkstra, liskov) on an
  isolated iteration branch, then judge the result with EXTERNAL gates (a deterministic gate tool,
  independent reviewers, a contract diff) and iterate until every gate is green or the budget is spent.
  Convergence is driven by the gates, not by the model re-grading its own output. Fails closed.
category: engineering
trigger: >
  When the user wants a task built end-to-end and held to an acceptance bar — "build X and make sure it
  actually passes review/tests/the spec", "iterate until it's right" — rather than a single best-effort
  pass; when shipping a not-quite-done change is costly enough to pay for gated iteration.
agents:
  - dijkstra
  - popper
  - liskov
  - lavoisier
shapes: [external-verification-gate, iterate-until-green, contract-first, worktree-isolation]
input: A build task (args.task). Optional args.maxIterations (default 4), args.integrationBranch (default abl/integration), args.baseRef (default HEAD).
output: >
  An accept/reject result with the iteration count and, on rejection, the residual unmet items. On
  acceptance the integration branch holds the gated build for the user to re-gate and merge to main.
zetetic_gate:
  logical: "The acceptance contract is compiled FIRST; every later phase is judged against it, not a moving target"
  critical: "Convergence uses best-effort in-loop checks (deterministic gate tool parsed in JS, independent reviewers, independent compare); because a Workflow cannot exec, these are agent-reported, so the AUTHORITATIVE gate is the human/CI re-running tools/acceptance-gate.sh on the integration branch with a real exit code before merging to main (arXiv:2310.01798)"
  rational: "Iteration depth is bounded (default 4); each iteration is an isolated branch merged to integration only on a VERIFIED green; a red build is never shipped"
  essential: "Each iteration's unmet items become the next iteration's backlog and are persisted to the semantic layer, so the loop converges instead of thrashing"
composes: [refine, web-to-semantic, semantic-ingest-loop, deep-research]
aliases: [build-loop, abl, iterate-until-green, autonomous-build]
hand_off:
  plan_unsound: "verify-plan rejected the plan — re-plan with the issues as backlog (no code written yet)"
  budget_exhausted: "iterations/tokens spent without a verified green — STOP, report residual; do not ship; raise args.maxIterations or narrow the task"
  oscillation: "if two iterations refute each other without converging, hand the loop to Maxwell (feedback-loop damping) before spending more budget"
---

## What this is

The genuinely-new outer controller for the autonomous build cycle. ~70% of the cycle already exists as
agents and skills; this skill wires them into a loop and adds the two missing pieces: **the iteration
controller** and **the whole-task acceptance gate**.

- **Vehicle:** a deterministic Workflow script (`.claude/workflows/autonomous-build-loop.js`) owns the
  loop, the iteration budget, and the convergence decision; each build round delegates to a built-in `general-purpose` builder agent
  carrying `GENIUS: dijkstra, liskov` (every delegation of the loop carries a `GENIUS:` line).
- **Acceptance gate (deterministic core):** `tools/acceptance-gate.sh` runs command-gates
  (zetetic-checker, test suites, contract-derived `checkable_cmd` checks) scoped to the iteration's
  commit range, aggregates their **exit codes**, and **rejects an empty diff**. The Workflow combines
  that with independent reviewer agents and a compare-to-contract pass.
- **Isolation:** the integration branch is created off an explicit `baseRef`; each iteration builds on
  `abl/iter-N` off it, and is merged into the integration branch only on a **verified** green; `main`
  is never touched by the loop.

## The loop

```
refine ─▶ contract ──┐                          (the spec everything is judged against)
setup ─▶ integration branch off baseRef          (so iter-1 can branch off it)
                     ▼
        ┌─▶ plan ─▶ verify-plan ─▶ build(builder commits to abl/iter-N)
        │                                   │
        │                                   ▼
        │   ACCEPT  =  TWO deterministic-gate runners agree (acceptance-gate.sh,
        │                  scoped to integration...iter-N; JS parses raw output)
        │           AND independent reviews (popper+feynman, plus taleb+boyd / simon+alexander
        │                  chosen from the diff's paths) all approve with evidence
        │           AND two compare-to-contract agents both find nothing unmet
        │                                   │
        │           green? ─yes─▶ VERIFIED merge abl/iter-N ▶ integration ; DONE
        └──no── discard iter-N + record residual ▶ backlog + semantic layer ◀──┘
               (stop after maxIterations or token floor — fail closed)
```

## Externality — the load-bearing constraint (read this)

A Workflow script **cannot exec a subprocess or read a file** — only agents run Bash. So the
deterministic gate is run *by an agent*. To keep the signal external rather than a model's self-report,
the controller:

1. keeps all determinism in the tool + committed configs (`memory/acceptance-gates.loop.yaml`);
2. has each runner return the tool's **raw stdout + exit code**, and decides in **JS** — it does not
   trust a model-emitted boolean;
3. runs **two independent runners** and requires them to **agree** (a forged verdict is caught by the
   honest run);
4. checks internal consistency (exit 0 ⟺ accepted, no leftover `unmet`).

This is the strongest anchor available *inside* a Workflow. The **authoritative** deterministic gate
runs *outside* it as a real exec, two ways (both read a real exit code, no model in the verdict):

- **Stop hook (automatic, recommended)** — `hooks/stop-acceptance-gate.py` runs
  `tools/acceptance-gate.sh` as a real subprocess on turn-end and **blocks the turn until it exits 0**.
  This is the mechanism the Claude Code best-practices guide names for a deterministic gate ("a Stop
  hook runs your check as a script and blocks the turn from ending until it passes";
  code.claude.com/docs/en/best-practices). Opt-in per run via a gitignored `.abl-gate.json` marker
  ({config?, diff_base?, diff_head?}); inert without it. Claude Code ends the turn after 8 consecutive
  blocks, bounding the loop.
- **Human/CI re-run (manual)** — run `tools/acceptance-gate.sh` on the integration branch yourself
  before merging to `main`.

The Workflow's in-loop checks drive *drafting and iteration*; the Stop hook / human re-run is the
real-exec *certification*. Validated against the Claude Code creator's loop template (see the
semantic-layer entry `claude-code-creator-loop-template`): our design matches it point-for-point, and
the Stop hook is the idiomatic real-exec gate it recommends.

## Invariants

- **INV-1 — contract first.** The refined acceptance contract (≥1 criterion) is compiled before any
  planning and is the only yardstick. `deterministic` criteria carry a non-null `checkable_cmd`;
  otherwise the criterion is `review`.
- **INV-2 — convergence judged by checks, not by the builder.** `accepted` is computed in the Workflow
  from a deterministic gate tool (parsed in JS, two runners), independent reviewer agents, and an
  independent compare (a reviewer-type agent, not the builder's lineage). These in-loop checks are
  **best-effort**: a Workflow cannot exec, so they are agent-reported, and two copies of the same model
  are not independent oracles (arXiv:2310.01798). The **authoritative** external gate is the human/CI
  re-running `tools/acceptance-gate.sh` on the integration branch (real exit code) before merging to
  main. The loop drafts and converges a candidate; the human/CI certifies it.
- **INV-3 — fail closed.** A disagreeing/failed gate runner, a non-JSON gate output, a missing
  reviewer, an empty gate set, an empty diff, a failed merge, or an exhausted budget all resolve to
  *not accepted*. A red build is never reported as shipped.
- **INV-4 — isolation, verified merge on green.** Each iteration is a branch off the integration
  branch, merged in only after a verified green merge (schema-checked `merged===true`); rejected
  iterations are discarded by the controller. `main` stays clean.
- **INV-5 — converge, don't thrash.** Every iteration's unmet items become the next iteration's backlog
  and are persisted to the semantic layer (cross-session memory), so a later run starts ahead.

## Invoke

```
Workflow({ name: 'autonomous-build-loop', args: { task: '<what to build>', maxIterations: 4, baseRef: 'HEAD' } })
```

The run is a real, heavyweight operation — it spawns the builder and reviewer agents and commits
code on `abl/iter-N` branches. Start it on a task with a clear success criterion. On success, **re-run
the deterministic gate on the integration branch yourself**, then merge to `main` (the loop never
pushes or touches main).

## Acceptance-gate config

- `memory/acceptance-gates.yaml` — standalone/manual runs; scopes to the **staged** diff.
- `memory/acceptance-gates.loop.yaml` — the loop's base gates; uses the `{files}` token and is run with
  `--diff-base <integration> --diff-head <iter-N>` so the scope is **tool-owned** (computed from git),
  not chosen by the builder via staging. The loop appends the contract's `deterministic` criteria as
  `origin: contract` gates before running it. Both configs are committed and deterministic; neither is
  assembled by a model.

## What it does NOT do

- It does not push or merge to `main` — it stops at the integration branch for human re-gating.
- It does not invent acceptance criteria — `compare-to-contract` judges against the contract as
  written; new requirements belong in a new contract (re-run).
- It does not let the builder grade itself, choose the diff scope, or select its own reviewers — the
  gate scope is a git commit range and the reviewer lenses are derived from the changed paths (INV-2).
