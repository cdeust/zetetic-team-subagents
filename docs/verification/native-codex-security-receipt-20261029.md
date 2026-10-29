# Native Codex security receipt as verdict proof, 2026-10-29

## Observed failure

cortex-viz PR 213 (re-render of #215/#216) passed every test job, but its
required `merge` check stayed `merge pending review`. Summary comment 6489153112:

    "security_review": {"commit_sha": "522f877...", "has_any_findings": null,
                        "has_unresolved_findings": null, "status": "completed"}
    codex-security-review:v1 {"headSha": "522f877...", "status": "completed", ...}

`ci_codex_reviews._review` returns pending while a flag is null; the existing
`resolve_security` only handles `has_any_findings: true`. Codex.yml resume run
40826790544 returned `{"action": "none"}`. No path left pending.

## Discriminating facts

- After `@codex security review`, Codex posted receipt 6491350304 (08:05:20Z):
  "Security review completed. No security issues were found in this pull
  request." with `Reviewed commit: 522f87761d`; the summary flags stayed null.
- Same shape on Cortex PR 829 (6491478435), Cortex PR 830 (6491726092),
  claude-mods PR 52 (6491339392) and PR 51 (6492031296), spec PR 163
  (6491660443, heading suffix "· _Automatically triggered_").
- Survey of 36 cdeust PRs with receipts: 13 security receipts, all with the
  no-issues sentence (11 plain heading, 2 automatic suffix). No receipt reports
  findings; findings appear as explicit summary flags (Cortex PR 805,
  zetetic PR 213/218), handled by the existing thread path.
- Cortex PR 833: automatic security review null/null, no security receipt.

Codex security-review documentation: "Check the task status and full report
before interpreting an empty comment result as a completed review with no
findings." An empty result is not proof; the receipt is the report's statement.

## Rule encoded

For a security review that is `completed`, bound to the head, flags null/null,
whose metadata names this repository, PR, head and `completed`:

| Receipts for the head (native Bot, authenticated editor) | Result |
|---|---|
| one or more, all "No security issues were found" | success, `reviews_complete` |
| none | blocked, `codex_security_verdict_missing` |
| any other wording | blocked, `codex_security_receipt_unrecognized` |

Unconfirmed metadata or a running review stays pending; explicit flags keep
their own path. The gate only names the cause: it never requests a review.
When a receipt arrives, Codex.yml resume re-runs the failed review job
(`_waited(review, READINESS)`), as for any completed proof.

## Change

- `ci_codex_review_comments.security_receipt`, `BLOCKING`, `BLOCKED_REASONS`.
- `ci_codex_reviews`: calls it after `resolve_security`; blocked set and reason
  from the table (module stays at the 300-line cap).
- Inline copies in `templates/ci/native/pipeline.yml` synchronized;
  `generated/pipeline.yml` refreshed from `render_ci.artifacts(native_review=True)`.
- `source.json`: adaptation `security-receipt-proof`; reader, comments module
  and review job digests updated; `original_security_reader` undoes the change
  so the pinned Cortex source digest still verifies.

## Verification (local)

- `tests/test_ci_native_security_receipt.py`: 11 tests, 6 real receipts as
  subtests plus negatives (code-review receipt, other commit, human copy,
  human edit blocked `editor`, unconfirmed metadata, unrecognized wording,
  running review, explicit findings, explicit clean verdict).
- `pytest tests/ -k 'ci_ or native or render or receipt'`: 604 passed.
- Exported consumer tests in a rendered tree, actionlint on the published
  export, and the rendered reader against live PR data: see the PR body.
