# Native security verdict: the owner resolves, not the flag (2026-10-29)

## Finding

Codex security review on session-optimizer PR 87 at `aaf8b6d`, discussion_r4412261213 (P2):
`_review()` returned `success` for `has_any_findings: true, has_unresolved_findings: false`
without the owner-aware `resolve_security()` check, which ran only for a null verdict.
A same-repository author who resolves their own finding thread makes the summary
explicit-clean, and the gate passes.

## Fix

- `ci_codex_review_runtime.resolve_security()` now accepts the explicit clean verdict as well
  as the null one, and checks each announced finding thread's `resolvedBy` against the
  repository owner.
  - An explicit clean verdict without that proof returns
    `{"state": "unresolved", "source": "owner_resolution_unproven"}`.
  - A null verdict without it still returns None, so the security receipt (#223) can decide.
- `ci_codex_reviews._reviews()` now calls it for a security review that is `success` with
  `has_any_findings: true`, in addition to `pending`.

## Evidence

- `tests/test_ci_native_security_owner_resolution.py` is built on PR 87's real summary at
  `aaf8b6d` (2026-10-29T12:24:01Z, repository anonymized), with the verdict the bot writes
  after a resolution:

  | Thread | Before | After |
  |---|---|---|
  | resolved by a non-owner contributor | `success` | `blocked` / `review_unresolved` |
  | resolved by the owner | no `resolution` recorded | `success`, resolution `github_review_threads` |
  | unresolved | `success` | `blocked` |
  | explicit unresolved verdict | `blocked` | `blocked` (unchanged) |

- `test_ci_native_*.py`: 125 passed, 39 subtests. This includes the receipt and
  current-finding suites, the source receipt with the new inverse, and the check that the
  embedded copies in `templates/ci/native/pipeline.yml` match the assets.
- The reader stays at its 300-line module cap.

## Observation for the convergence agent: automatic security reviews leave no receipt

On claude-mods PR 52, head `c5666ee`:

| Time (UTC) | Event |
|---|---|
| 12:04:27 | Codex code review completed, trigger "New commits". |
| 12:11:19 | Codex security review completed, trigger "New commits". The summary kept `has_any_findings: null`, and **no receipt comment was posted**. |
| 12:13:02 | Pipeline run 40870029583, attempt 2: `codex_security_verdict_missing`. |
| 12:13:33 | Manual `@codex security review` (comment 6496348481). |
| 12:18:39 | Receipt 6496465084: "No security issues were found". |
| about 12:19 | Attempt 3: `review` and `merge` green. #52 merged at 12:20:33. |

Session-optimizer PR 87, head `aaf8b6d`, shows the same pattern:
- the automatic security review completed with no receipt;
- the manual request (12:16:42) produced the receipt with the finding above.

So the gate needs one `@codex security review` per head SHA. The ci-autonome manager and
the Cortex #834 planner are responsible for posting it.
