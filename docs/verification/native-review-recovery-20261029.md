# Automatic native review recovery, 2026-10-29

## Behavior and sources

The existing trusted-main event and scheduled reconciliation paths now request native work automatically. An authenticated completed security review with an unknown verdict requests `@codex security review`. Positive authenticated current-head unresolved findings or actual failed Pipeline category jobs request `@codex fix the review feedback`. Unknown flags remain pending, real findings remain blocking, and the existing merge authorization/resumption policy is unchanged.

Primary trigger contracts: https://learn.chatgpt.com/docs/security/security-review and https://learn.chatgpt.com/docs/third-party/github#act-on-review-findings. Owner design: https://github.com/cdeust/ci-autonome/blob/f9d4591/docs/superpowers/specs/2026-10-28-ci-autonome-design.md. It requires bounded patience but does not define a numeric retry limit; this patch retains the existing five-minute schedule/worker operational limits and adds no sleeps, polling retries, or invented retry constants.

A durable request marker binds repository, PR, immutable head, and kind. Only original-owner User or the immutable GitHub Actions Bot actor can establish it; another editor cannot suppress recovery. Bot identity was verified through `GET /users/github-actions[bot]`: node_id `MDM6Qm90NDE4OTgyODI=`. Fresh live-head, native-proof, latest-run and attempt-job reads precede request creation. A marker arriving before the write boundary prevents another request. The two mutation workers gain issues:write and retain the same per-PR concurrency group; discovery stays read-only.

FIX prompts name the authenticated native summary ID and exact server-validated failed run/attempt/job log commands. Other PR comments and embedded instructions are untrusted data. Workflow fixes must use the canonical render-ci source; the task cannot change verdicts, weaken gates, resolve threads, or merge. Requests never authorize a merge or treat a native task as completed. Failed CI requests authenticate server identities/head/status; the existing executed-definition proof remains the merge authorizer, with no additional definition freshness gate.

The owner-scoped `ci_codex_review_controller.py --once --inventory <json> [--dry-run]` uses the same discovery and coordinator. Inventory schema is exactly `{ "owner": "cdeust", "repositories": ["cdeust/Cortex", "cdeust/ai-architect-mcp-codebase"] }`; foreign/duplicate/malformed entries fail before API access. It uses connected gh, restores its per-PR process environment, prints flushed per-repository/PR progress, and isolates repository API errors while returning a nonzero aggregate result.

## Verification

Before implementation, the actual event/server fixture returned action:none for completed unknown security; native FIX cases likewise returned none. New contracts failed before the new behavior. Root's missing-summary FIX replay case reproduced EvidenceError(protocol), then passed after FIX dedup stopped trying to order nonexistent native summaries.

- Canonical standard-library native contracts: `python3 -B -m unittest discover -s templates/ci/native/assets/scripts/tests -p 'test_ci_codex_review_*.py'`: **125 tests, OK**.
- Consumer/rendering checks execute the delivered contracts under Python `-S`, including exact unknown/FIX/failed-category cases. Native contract jobs now run those tests explicitly before ci.json validation, so consumer pytest testpaths cannot omit them.
- `actionlint -shellcheck= templates/ci/native/assets/.github/workflows/Codex.yml templates/ci/native/generated/pipeline.yml`: exit0.
- `bash tools/tests/render-ci/run-tests.sh`: 7 passed, 0 failed.
- No verdict reader, merge policy, legacy Fix block, or Claude workflow changed by this worker.

## Remaining acceptance and limits

Root owns publication and actual execution. Comment creation alone does not prove the provider accepted a Bot mention, started a native fix task, pushed a correction, or produced a green successor Pipeline. Those are independent hosted acceptance receipts; the official trigger documentation does not establish Actions-bot acceptance.

GitHub issue-comment creation has no conditional-create API. Hosted workers serialize through the existing per-PR group; the bootstrap controller must not race an enabled hosted controller. No repeated mention is issued while a trusted head/kind receipt exists. A later still-unknown native result produces the diagnostic provider_unknown_after_request and remains pending. Native FIX receipts work even when no native summary exists yet.

The isolated worktree is `.claude/worktrees/native-review-recovery-20261029`, branch `fix/native-review-recovery`, based on c80a6dd (source216 included). Root must preserve later source217/218 work during integration. Creation hook registered root ownership; the worker left that ledger unchanged. No external writes were performed.
