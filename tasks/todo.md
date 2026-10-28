# Advisor composition (2026-09-17)

- [x] Bind the requested behavior to Claude Code's native `/advisor`.
- [x] Deliver the separate advisor composition in PR #142 using the checkable plan in
      [advisor-goal-review.md](advisor-goal-review.md).

# GOA Phase 0 Codex replay (2026-08-04)

- [x] Resume `/memories/zetetic-team-subagents/checkpoint.md` and read the
      merged Phase 0 protocol at commit `3829f54`.
- [x] Determine whether Codex `sol`, `luna`, and `terra` are independent model
      families or configurations of one family, using verifiable local model
      metadata.
- [x] Inspect the local 351-case gold set without exposing case contents and
      prepare blind, isolated output paths.
- [x] Run three distinct Codex raters: Sol, Terra, and Luna. Treat them as
      separate model validations but one GPT-5.6 family for cross-family claims.
- [x] Validate output schema/completeness and score the replay without using
      adjudication outputs as input.
- [x] Record exact model identities, commands, results, limitations, and the
      next human-arbitration action.

## Review

All three models produced 351 valid, uniquely identified labels. Independent
recalculation confirmed every schema check, partition, and agreement statistic.
Pairwise Cohen kappas within GPT-5.6 are Sol/Terra 0.641, Sol/Luna 0.623, and
Terra/Luna 0.591. Against the historical raters, all three align more often with
B on shape decisions.

The durable private archive is
`~/.claude/zetetic/goa-phase0/replays/2026-08-04-codex-gpt56/` (moved there from
`~/.claude/goa-phase0/` by `setup.sh`, issue #136); the public, non-sensitive
method/report is `docs/goa-phase0/REPLAY-CODEX-GPT56-2026-08-04.md`.

Limitation: historical A/B/C files were OS-quarantined, and a trace audit found
no access to earlier Codex outputs, but cross-Codex non-readability was not
enforced by a separate UID or explicit read-denial. Future runs must close that
technical gap. PR #92 remains blocked on explicit human arbitration.

Identity decision: Sol, Terra, and Luna are distinct model IDs/tiers inside the
single GPT-5.6 family. Sol supplies the cross-family comparison; the requested
Terra and Luna runs add within-family, cross-model robustness. All three must be
reported, without miscounting them as three independent families.

## Shared Claude Code / Codex gates

See [implementation and validation](shared-host-gates.md). Native hook trust remains an owner action.


## Native resumption contracts, 2026-10-28

- [x] Verify Spec159 findings and current canonical source.
- [x] Reproduce absent delivered/executed contracts (two failures).
- [x] Deliver the existing Cortex decision/coordinator contracts as native assets.
- [x] Execute those contracts through Spec ci.json and verify renderer integrity.
- [x] Obtain independent root diff review; publication and cleanup follow verification.

Thread resolution is webhook-only, not an Actions event. Keep the unsupported trigger absent; controller reconciliation is owned by root.

Review: 59 canonical contracts; 50 renderer/native tests plus33 subtests; 78 Spec Python CI contracts. See docs/verification/native-resumption-contracts-20261028.md.

## Native scheduled reconciliation, 2026-10-28

- [x] Verify supported schedule events and public runner billing in GitHub documentation.
- [x] Reproduce missing fallback helper with ten failing contracts.
- [x] Implement paginated discovery and exact existing-policy resumption.
- [x] Add trusted-main discovery and per-PR workers to Codex.yml.
- [x] Validate 69 native contracts, 52 renderer contracts plus33 subtests, and 88 Spec CI contracts.
- [x] Obtain independent root review of helper and workflow.

Review: see docs/verification/native-scheduled-reconciliation-20261028.md. Hosted scheduled acceptance requires publication to main.
