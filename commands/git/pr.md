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
   | Item / chemin du diff | Preuve (test / commande+sortie / mesure / analyse) |
   |---|---|
   | edge cases: [énumérés] | [tests] |
   | failure paths: [chaque bras/fallback/early-return] | [test assertant l'effet observable, émission du signal incluse] |
   | deadlocks | [analyse écrite ou « no concurrency touched » si vrai] |
   | scalability | [dimensions de croissance nommées / mesure] |
   | fonctionnel exécuté | [sortie de run citée] |
   | lisibilité/simplicité | [passe faite, indirections retirées] |
   | normes/conventions | [règles passées, conventions voisines vérifiées] |

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
