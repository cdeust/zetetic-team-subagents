# Zetetic Pull Request

Create a pull request with zetetic-standard review and documentation.

## Instructions

1. Run the `/review` skill (skills/engineering/review.md) on all changes vs the base branch.

2. Build the **Completion Ledger** (rules/coding-standards.md §13.2 — MANDATORY, the PR is invalid without it):
   - Enumerate every code path introduced by `git diff base...HEAD` (branches, early returns, error arms, fallbacks, degraded modes).
   - One row per §13.1 baseline item + one row per enumerated path, each with EVIDENCE (asserting test name, command + quoted output, measurement, or written analysis — never prose assurance).
   - Any row without evidence ⇒ the PR is NOT finished: stop here, complete the implementation first.

3. Generate a PR description:
   ```
   ## Summary
   [1-3 bullet points of what changed and why]

   ## Completion Ledger (§13)
   Walk the FULL §13.1 checklist (A1-A6, B1-B3, C1-C3, D1-D3, E1-E4, F1-F2, G1-G5, H1-H6).
   EVERY item appears with status `done` + evidence, or `N/A` + one-line justification.
   An item that is neither means the implementation is not finished — do not open the PR.

   | §13.1 item | Status | Evidence / justification |
   |---|---|---|
   | A1 happy paths | done/N/A | [quoted run output] |
   | A2 edge cases: [enumerate them] | done/N/A | [tests] |
   | A3 failure paths: [enumerate every arm/fallback/early return] | done/N/A | [test asserting the observable effect, signal emission included] |
   | A4 boundary validation | done/N/A | [tests incl. malformed input] |
   | A5 invariants & partial failure | done/N/A | [stated contracts / tests] |
   | A6 idempotency/retry | done/N/A | [semantics or justification] |
   | B1 deadlocks | done/N/A | [written analysis, or "no concurrency touched"] |
   | B2 races/atomicity | done/N/A | [analysis / tests] |
   | B3 cancellation safety | done/N/A | [analysis / tests] |
   | C1 scalability | done/N/A | [growth dimensions named / measurement] |
   | C2 resource lifecycle | done/N/A | [leak analysis / bounded pools] |
   | C3 hot-path measurement | done/N/A | [before/after numbers] |
   | D1 injection | done/N/A | [vetted helper used + adversarial test] |
   | D2 untrusted data | done/N/A | [sources listed + handling] |
   | D3 secrets/privilege | done/N/A | [check done] |
   | E1 API/schema compatibility | done/N/A | [additive proof / version bump] |
   | E2 consumers verified | done/N/A | [named consumers + read paths checked] |
   | E3 persisted-data migration | done/N/A | [one-shot migration / old-data test] |
   | E4 cross-platform | done/N/A | [addressed / platform-independent] |
   | F1 failure signals asserted | done/N/A | [emission test + quiet-nominal test] |
   | F2 degraded modes explicit | done/N/A | [named in output/schema + docs] |
   | G1 path→test ledger complete | done | [the table below] |
   | G2 regression tests for fixed bugs | done/N/A | [test fails pre-fix] |
   | G3 tests deterministic/isolated | done/N/A | [unique temp dirs, repeated parallel runs] |
   | G4 negative assertions | done/N/A | [tests] |
   | G5 full suite + gates | done | [quoted output] |
   | H1 standards §1-§9 | done | [compliance report] |
   | H2 readability, no dead code | done | [pass done] |
   | H3 conventions + one language per file | done | [checked] |
   | H4 CHANGELOG + docs | done/N/A | [entry ref] |
   | H5 commit hygiene | done | [conventional, logic/format separate] |
   | H6 CI green | done | [run link — before requesting merge] |

   ### Path→test table (G1)
   | Diff path (every branch/arm/fallback/early return) | Asserting test |
   |---|---|
   | [path] | [test name] |

   ## Zetetic Checklist
   - [ ] No invented constants (zetetic-checker passed)
   - [ ] Sources cited for non-trivial claims
   - [ ] Difficulty book updated (if applicable)
   - [ ] Tests cover new behavior
   - [ ] Layer boundaries respected

   ## Review findings
   [Summary of /review output — critical items must be resolved before merge]
   ```

4. Push the branch and create the PR with `gh pr create`. A PR whose ledger has gaps goes up as **draft only**, never ready-for-review.

5. Report the PR URL.

$ARGUMENTS
