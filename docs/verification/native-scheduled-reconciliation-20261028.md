# Native scheduled review reconciliation, 2026-10-28

Spec159 findings4395992283 and4395992285 exposed a missing completion wake after thread resolution. GitHub supports the thread webhook but no corresponding Actions event. Codex.yml retains ordinary comment/workflow completion handling and adds a five-minute schedule plus workflow_dispatch fallback.

Sources: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule and https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run#standard-github-hosted-runners-for-public-repositories . Five minutes is the documented minimum. Standard public runners are free; scheduling can be delayed and inactive public repositories can be disabled after 60 days. All three target repositories were verified public through their repository API.

Discovery follows all PR pages, selects eligible same-repository PRs, requires successful prerequisites, and uses the existing authenticated proof and resumption policy. Each matrix worker repeats current proof before the exact job rerun under existing per-PR concurrency. Per-PR protocol or transport failures are sanitized and isolated. Global malformed pagination fails closed. No model is invoked.

Validation: ten new helper contracts initially failed before implementation and now pass; 69 canonical native contracts pass; 52 targeted renderer/native tests plus33 subtests pass; 88 Spec Python CI contracts pass through the actual ci.json command. actionlint, Ruff, source and craftsmanship checks pass. Root independently reviewed and approved the final helper and workflow before publication. Pipeline body and unrelated consumer settings remain unchanged.

The helper and workflow execute from main. Local tests and PR publication do not establish hosted scheduled acceptance. After merge, workflow_dispatch can exercise this supported fallback without fabricating a bot event.
