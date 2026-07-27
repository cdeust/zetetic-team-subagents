# OpenSSF Scorecard posture and finding dispositions

`.github/workflows/scorecard.yml` runs the OpenSSF Scorecard analysis on a
schedule and uploads its SARIF to GitHub code scanning. Several Scorecard checks
are repository-policy signals rather than code defects. A contributor cannot
resolve them inside a diff, because their subject is repo configuration, project
scale, or immutable history. This file is the written, source-controlled record
(rules/coding-standards.md §8) of how each such finding is dispositioned, so the
posture is shown in the tree rather than left as a permanently-open alert.

Each declined finding below is also dismissed through GitHub's code-scanning
dismissal flow with a comment pointing back here. Dismissals persist across
re-runs, because Scorecard alerts are keyed by rule id.

## Dispositions

### `DependencyUpdateToolID` — satisfied

`.github/dependabot.yml` configures Dependabot for the `github-actions`
ecosystem, which is the repo's only external supply-chain surface. The alert
closes on the next Scorecard run after merge.

### `SASTID` — satisfied going forward; historical residual declined

CodeQL (`codeql.yml`) statically analyses the entire Python executable surface
on every push to `main`, every PR, and weekly; `shellcheck.yml` covers the shell
surface. Scorecard samples the last 30 commits and credited 7; the uncredited
commits predate the CodeQL workflow. That residual cannot be earned by rescanning
immutable history, and it rises automatically as post-workflow commits accrue.

### `FuzzingID` — declined

This is a personal-scale repository of Markdown agent definitions plus
shell/Python glue. It exposes no long-running parser, protocol, or
untrusted-byte-stream surface that a fuzzing harness (OSS-Fuzz or equivalent)
would exercise. A fuzz target would be dead scaffolding (§9).

### `CIIBestPracticesID` — declined

The check wants a CII/OpenSSF Best Practices badge, earned by external
self-certification at bestpractices.coreinfrastructure.org. The underlying
practices it certifies are already present in the tree: `SECURITY.md`,
`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, and the always-on CI
gates. The external badge registration sits out of band from any repo change.

### `CodeReviewID` — declined

The check credits changesets approved by a second reviewer (0 of 15). This is a
single-maintainer repository, and GitHub does not permit self-approval, so
"approved changesets" is structurally unreachable without a second maintainer.
Review rigor is instead enforced by the always-on hard CI gates that block every
PR: Craftsmanship Checker, Redaction Sweep, Tools Regression Suite, Zetetic
Standard Checker, `shellcheck`, and CodeQL.

### `BranchProtectionID` — declined

Full credit requires branch protection with required reviews on `main`. Requiring
reviews on a single-maintainer repo would deadlock all merges, because there is
no second approver (see `CodeReviewID`). The repo relies on the always-on CI
gates above, which run on every push to `main` and every PR, as the enforced
quality bar in place of review-count protection.

## Re-evaluation triggers

These dispositions are conditioned on the repo's current scale. Revisit if:

- a second maintainer joins, at which point `CodeReviewID` and
  `BranchProtectionID` become satisfiable: enable required reviews and re-open;
- the repo grows a parser or untrusted-input surface, at which point `FuzzingID`
  is worth a real harness;
- the project pursues the OpenSSF Best Practices badge, at which point
  `CIIBestPracticesID` is satisfied on certification.
