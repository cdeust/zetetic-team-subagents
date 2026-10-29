# Positive native security receipt proof

Primary artifact: https://github.com/cdeust/zetetic-team-subagents/pull/219#issuecomment-6491639753. Native summary6491366848 binds security to full commit cf9b1d491692d1ae98dbf51d427c88638a67e882 with completed status and null flags. The receipt explicitly says no security issues were found, displays cf9b1d4916, and links one provider report. Native actor BOT_kgDOC98s_g and pristine receipt editor metadata were verified through GraphQL; REST identifies App1144995. GitHub uniquely resolves commits/cf9b1d4916 to that full SHA.

The new canonical ci_codex_review_receipts.py recognizes only the observed versioned security receipt format. It requires the exact explicit clean statement, one reviewed commit, one strictly shaped provider report, native immutable actor/editor, same repository/PR/full-SHA completed companion metadata, and unique GitHub resolution of a displayed short commit. The observed ten-hex display and 32-hex opaque report suffix come from the primary artifact, not a tuning threshold. A full displayed SHA is accepted only as the exact target.

Raw null flags remain unchanged. The separate resolution records source, receipt ID, full commit, and report URL. It cannot override positive findings, explicit unresolved state, running reviews, stale summaries/receipts, forged actors/editors, API ambiguity/errors, truncation, conflicting bindings, or multiple reports. A newer malformed security receipt cannot fall back to an older clean receipt.

The same helper is shipped as a native asset and embedded/preloaded as the fourth trusted module before the reader. Inline byte identity, shared exception types, upstream inverse adaptations and rendered consumer execution are verified. No candidate helper is imported by the embedded trusted path.

Verification on final implementation:

- RED: the actual reader returned pending/false for the positive explicit receipt, and failed to reject its human-edited variant; two new contracts failed before the path existed.
- GREEN: 14 focused receipt contracts; 139 complete canonical native contracts.
- Focused renderer/security integration: 40 passed plus 33 subtests. This is not the repository-wide unit suite or hosted acceptance.
- Measured doc-count-check: 32 claim instances verified, zero problems. No MCP tool was added or count guessed.
- actionlint on native generated Pipeline and Codex completion workflow: exit0.

Actual public read-only probe is retained in ci-autonome/tasks/evidence/native-security-clean-receipt-20261029.json. It establishes security resolution for old cf9b1d..., while overall old-head state remains pending because code review is independently bound to older c9329d.... Current draft head29d6a55... also remains pending/incomplete. The old receipt cannot clear that newer head. The private report body was not read; no claim about its contents is made beyond the authenticated public receipt.

This local commit follows37ba3bb and must be cherry-picked separately into the current source219 branch, preserving its marketplace count73 and concurrent main/post-merge alias work. Root owns publication, fresh-head native reviews and hosted CI. No remote writes were performed by this worker.

## Independent-review contradiction guard

The independent reviewer reproduced a false-clean case on f8e4380: a current authenticated both-null summary announced security finding123, while an older same-head clean receipt established success. Two new contracts reproduce this RED, including malformed/incomplete/count-mismatched sections. The helper now rejects current Security/Blocking/Advisory findings sections and native security-finding markers before considering an older clean receipt. Null flags never cancel positive body evidence.
