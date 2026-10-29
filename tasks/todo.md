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

Review: 59 canonical contracts; 50 renderer/native tests plus 33 subtests; 78 Spec Python CI contracts. See docs/verification/native-resumption-contracts-20261028.md.

## Native scheduled reconciliation, 2026-10-28

- [x] Verify supported schedule events and public runner billing in GitHub documentation.
- [x] Reproduce missing fallback helper with ten failing contracts.
- [x] Implement paginated discovery and exact existing-policy resumption.
- [x] Add trusted-main discovery and per-PR workers to Codex.yml.
- [x] Validate 69 native contracts, 52 renderer contracts plus 33 subtests, and 88 Spec CI contracts.
- [x] Obtain independent root review of helper and workflow.

Review: see docs/verification/native-scheduled-reconciliation-20261028.md. Hosted scheduled acceptance requires publication to main.

## Native discovery review corrections, 2026-10-28

- [x] Verify actual native Claude findings and current canonical main.
- [x] Add paginated GraphQL status-rollup prefilter and serialize discovery.
- [x] Preserve existing policy readiness-repair authorization and remove duplicate PR read.
- [x] Prove API-failure stop, CLI/output boundaries and RED/GREEN contracts.
- [x] Verify 77 canonical, 52 renderer plus 33 subtests, and 96 Codebase contracts.

Review evidence: docs/verification/native-discovery-review-corrections-20261028.md. Root independently reviews final artifacts before publication.

## Native proof-first followup, 2026-10-28

- [x] Verify actual second native Claude findings and observed API/error/job evidence.
- [x] Authenticate head proof before REST discovery without vetoing readiness repair.
- [x] Preserve sanitized typed API categories and isolate only known per-PR missing resources.
- [x] Bound all completion jobs to one existing schedule period.
- [x] Verify 88 native contracts, 54 source tests plus 33 subtests, Cortex Ruff and actual craftsmanship scanner.
- [x] Obtain explicit root production review approval; provenance and staged gates follow.

Review evidence: docs/verification/native-proof-first-20261028.md.

## Native gate-name groups, 2026-10-28

- [x] Read real native Claude report and verify current canonical main.
- [x] Reproduce gate-name collisions before the fix.
- [x] Preserve a superset hint using CheckRun groups and full-policy authorization.
- [x] Exercise normalized proof API categories through actual callbacks.
- [x] Verify95 native contracts and54 source contracts plus33 subtests; actual Cortex gates pass.
- [x] Obtain explicit independent root production approval.

Evidence: docs/verification/native-gate-groups-20261028.md.

## Native executed-workflow authorization, 2026-10-29

- [x] Inspect source ownership, open PRs and actual native P1.
- [x] Demonstrate RED: fake workflow with successful authenticated job metadata merges.
- [x] Bind authorization to GitHub WorkflowRun.file and exact run/attempt.
- [x] Permit installed definitions and protected canonical renderer upgrades.
- [x] Verify focused native tests, renderer/inventory gates and actionlint (144 passed).
- [x] Complete full unit/coverage verification and preserve final receipts.
- [ ] Publish source PR, verify remote head and dispose owned worktree.

Review: docs/ci-workflow-proof.md records source contracts and hosted acceptance limits.

## Native rerun merge identity, 2026-10-29

- [x] Read cortex-vision PR5 finding4408735600 and canonical merge-name expression.
- [x] Reproduce full-history failure against the same current graph without history.
- [x] Fold both merge display names as one logical job, retaining the winning payload.
- [x] Verify 101 native contracts, 28 rendering/delivery contracts, and 7 render-ci shell checks.
- [ ] Root diff review, publication, hosted CI, and registered-worktree disposal.

Review: [source evidence](../docs/verification/native-rerun-merge-identity-20261029.md).

## Portable native authorization contract export, 2026-10-29

- [x] Read actual Spec P1 and baseline/source evidence; coordinate P2-owned paths.
- [x] Demonstrate missing exported executable contract RED (2 failed, 1 passed).
- [x] Export stdlib tests of actual generated resolver and invoke before configured unit jobs.
- [x] Verify combined 117 source contracts + 33 subtests, 113 generated consumer tests, mutation RED and actionlint.
- [ ] Hand exact local source evidence to root for publication; no external writes here.

## Automatic native review recovery, 2026-10-29

- [x] Verify actual native protocol, official triggers, and approved owner design.
- [x] Reproduce stalled unknown security and missing native FIX behavior.
- [x] Add authenticated head/kind request dedup, fresh evidence, fixed task prompts, and automatic event/schedule routing.
- [x] Deliver once/dry-run inventory controller and explicit consumer contract execution.
- [x] Verify 125 canonical native contracts and rendered consumer checks.
- [ ] Root review/publication, hosted Bot acknowledgement, native correction/new-head CI, and registered cleanup.

Review: docs/verification/native-review-recovery-20261029.md.

## Positive native security receipt, 2026-10-29

- [x] Verify actual native actor/editor, explicit clean body, companion full SHA and unique GitHub short-commit resolution.
- [x] Reproduce missing positive proof, then add strict parsing with forged/stale/truncated/ambiguous negative contracts.
- [x] Embed the same helper in canonical generated native CI and deliver its consumer contracts.
- [x] Verify 139 native contracts, 40 focused integration checks plus 33 subtests, measured doc counts and actionlint.
- [ ] Root integrate into current source219 and validate fresh-head hosted reviews/CI.

Review: docs/verification/native-security-clean-receipt-20261029.md.

## Exact native security transport, 2026-10-29

- [x] Verify the actual marked-command/code-review mismatch and exact-only security completion.
- [x] Send only the exact native security command, with separate authenticated outbox control and explicit partial states.
- [x] Preserve accepted FIX body; cover replay, lost acknowledgements, head/proof races, actor/editor linkage and untrusted controls.
- [x] Apply measured PR-write permission correction; preserve private no-schedule rendering.
- [ ] Root publish the combined source, run full hosted CI and exercise the complete outbox against the blocked queue.

Review: docs/verification/native-security-exact-transport-20261029.md.

## Source219 and source220 integration, 2026-10-29

- [x] Fetch protected main and merge normally into the published integration branch.
- [x] Preserve shared source219 receipts/outbox and source220 post-merge alias folding.
- [x] Regenerate canonical native export and merge metadata without dropping adaptations.
- [x] Add four portable regressions against the actual generated authorization controller.
- [x] Verify focused CI/native/portable suites, source receipts, doc counts and actionlint.
- [ ] Hand local merge commit and durable evidence to root for publication.

Review: protected main fd9cd91431bbc6cdce5d3e4d2030f0669aeddeb6 merged into
published source219 head39d31dc5c2c289a74a06fc5f4df8fb51977ac377. The combined
source CI suite passes546 tests plus33 subtests; native contracts pass156;
portable actual-workflow authorization passes16. Removing only the alias mapping
in a disposable generated workflow produces two assertion failures and one error,
while the original12 contracts and inverse pending-to-merge case still pass.
Doc counts verify32 claims with zero problems; actionlint and staged strict
zetetic, craftsmanship and redaction gates pass. Full combined hosted CI and
fresh exact-head native reviews remain required after root publication.
