# Native gate-resumption contracts, 2026-10-28

Spec159 finding4395992285 identified missing tests for resumption decisions, event authorization, retained partial-attempt results and emitted rerun requests. The native renderer now delivers seven test/fixture files adapted from the reviewed Cortex f4831d159c181b5e170c984f703ed733819f188e contracts. Every delivered file has a digest in templates/ci/native/source.json; copied originals have their own source hashes there.

No production evidence helper or completion workflow changes. The additional direct-reconciliation tests exercise resume with the existing current-head and thread-resolution proof. They verify the exact merge-job POST, reject non-owner/unresolved evidence, reject stale heads and unrelated failures, and re-read resolution immediately before a rerun. API calls are mocked at the gh boundary; authorization and decision code execute normally.

Measured verification:

- Before adding delivered contracts, tests/test_ci_native_resumption.py reports two failures and one pass: missing test assets and absent executable contracts.
- The canonical decision/coordinator suite reports 59 tests passing.
- Native-profile and renderer tests report 50 passed and 33 subtests passed.
- Spec ci.json now discovers all test_ci_codex*.py contracts in its regression category. Executing that exact command reports 78 tests passing.
- Spec's existing pnpm regression suffix is unchanged, SHA256 c995fbe0dc1a26541d116b7a7b38e99fa564727e0ad36c96e075e9c6c58910c1. Other ci.json categories are byte-equivalent after JSON parsing. The TypeScript application was not changed or rebuilt for this Python test delivery.
- Documentation count and command gates pass with zero problems. Workflow rendering changes only the two existing source-digest comments in Spec.

Spec159 finding4395992283 suggested pull_request_review_thread as an Actions trigger. It is documented as a webhook, but is absent from GitHub's supported Actions event catalog. The actionlint stdin probe rejects it as an unknown Webhook event. The supported completion workflow remains unchanged, and tests require unsupported thread/dispatch events not to authorize a rerun.

An existing external controller may call ci_codex_review_event.resume(repo, trigger) with number, expected sha and optional run_id, plus EXPECTED_PR in its environment. This delivery tests that entry point but does not install a controller, webhook receiver or scheduled workflow. It does not claim automatic thread-resolution reconciliation is deployed.

Sources:

- https://github.com/cdeust/ai-architect-mcp-spec/pull/159#discussion_r4395992285
- https://github.com/cdeust/ai-architect-mcp-spec/pull/159#discussion_r4395992283
- https://github.com/cdeust/Cortex/tree/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review_thread

Root independently reviewed the direct full-proof tests and approved publication after verification. Source base: d99d75183a4f32a725d98e516b4816f2d1c61d28. Spec base: 04d27a4811842ea13a1d5614e23ce552e4921aa0.
