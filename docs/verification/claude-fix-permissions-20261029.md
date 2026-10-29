# Claude fix permissions, 2026-10-29

Base: `24bd8d7826f46e0767a5b3ce46ff8e9eb8ddad8a` (PR217 retained).

The canonical native owner workflow passed `--permission-mode auto` after the
pinned action's `acceptEdits`. The pinned parser uses the last non-accumulating
flag, so the workflow replaced the action's workspace edit approval. Remove that
override and explicitly approve the project's validation/git tools. Keep owner
event authentication, filter comment context to the owner, and execute a PR target
check before checkout/action: same repository, non-default head branch, API errors
fail closed. Issues without a PR still use tag mode's new task branch.

The automatic legacy `Fix` already approved Edit/Write and validation commands,
but its prompt prohibited `.github/workflows/pipeline.yml`. It now selects
`acceptEdits` explicitly and directs generated workflow changes through their
canonical source and `render-ci`, on the PR branch. The repository workflows were
regenerated with `python3 scripts/lib/render_ci.py .`.

The legacy workflow bootstrap skip now applies to non-owner workflow PRs. A
same-repository PR whose authenticated author is the repository owner can run
review and automatic Fix even when it edits the workflow. Bot follow-up commits
on that owner PR still repair failed checks. The guard rejects missing/default
head branches before any automatic Fix; the job's fork/draft/Dependabot exclusions
remain. New execution contracts failed four cases before this guard change and
passed afterward.

## Primary sources inspected

- [Pinned tag mode](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/modes/tag/index.ts): workspace edit mode, headless permission behavior, required tools.
- [Pinned argument parser](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/base-action/src/parse-sdk-options.ts): last permission mode wins; tool allowlists accumulate.
- [Pinned git authentication](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/github/operations/git-config.ts): origin rewritten to action App token.
- [Pinned push wrapper](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/scripts/git-push.sh): ordinary `git push origin`.
- [Pinned checkout authentication](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/src/git-auth-helper.ts): SSH configuration persists only when requested.
- [Pinned custom App manifest](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/github-app-manifest.json): its defaults omit Workflows permission; this does not establish the installed public App's permissions.
- Exact npm CLI `2.1.306` help: `acceptEdits` is supported; `--permission-prompts none` denies anything requiring a prompt. Inspected native package from the registry, without running a model session.
- Live Cortex `claude.yml`: already inherits tag mode and limits comment context to the owner.

## Validation

New owner contracts before patch: `2 failed, 1 passed` (auto override and absent SSH
proposal). The SSH proposal was removed before delivery; App authentication from
PR217 remains unchanged. New automatic Fix contract before patch: `1 failed`
(missing explicit workspace mode). Final contracts additionally execute the
actual PR target check for same-repository, fork, default-branch, missing
repository and API-error inputs.

`python3 -m pytest -q tests/test_ci_*.py`: 529 passed, 33 subtests passed.
`bash tools/tests/render-ci/run-tests.sh`: 7 passed, 0 failed.
`actionlint` on native `claude.yml` and both changed rendered workflows: exit 0.
`git diff --check`: exit 0.

## Hosted acceptance still required

No model run, real push, secret write, remote branch or PR was performed by this
worker. Actual project-file and workflow-file push acceptance requires a real
owner-authorized run. No SSH secret is required by this patch. A repository SSH
push URL can preserve SSH push across the pinned action's origin rewrite if the
real App rejects workflow updates; that transport is not included here.

Native read-only review and merge verdicts remain intact. Non-owner legacy
workflow PRs retain the bootstrap skip; owner PRs use the explicit branch/author
authorization above. Automatic native review recovery belongs to its separate
controller change.

## Security correction for finding4409864800

[The native P1 finding](https://github.com/cdeust/zetetic-team-subagents/pull/218#discussion_r4409864800)
identified a public-comment injection path into automatic workflow repairs. Fix
now consumes a JSON snapshot collected before the model starts. The collector
lists issue comments, inline comments and reviews, then obtains each body with
author/editor attribution from the same GraphQL node. It accepts the repository
owner's immutable User identity or the exact native Claude/Codex Bot identity.
Edited bodies require the original actor as editor. Missing provenance, API
errors, wrong node identities and a head move fail closed before publication.

The source is `tools/ci_claude_fix_context.py`, embedded byte-for-byte in the
canonical pipeline and verified by an identity test. The Fix prompt no longer
reads all public comments; its broad gh allowlist is replaced with scoped log,
diff and publication commands. It explicitly excludes unfiltered feedback.

Workflow-changing Claude commits now always run the separate read-only Review
step, including on green bot heads. Only non-workflow Claude commits retain the
old duplicate-review optimization. A new model review can repair findings on
each changed workflow head without introducing a manual approval gate.

Primary API evidence on 2026-10-29:

- `GET /apps/claude`: registered public App grants Workflows write, Contents
  write and Actions write. The pinned custom App manifest above does not describe
  this registration. SSH is not indicated by that manifest omission.
- `GET /users/claude[bot]`: `209825114`, `BOT_kgDODIGtWg`.
- `GET /users/chatgpt-codex-connector[bot]`: `199175422`, `BOT_kgDOC98s_g`.
- GraphQL schema introspection confirmed Actor IDs require User/Bot fragments;
  all three feedback node types expose editor and lastEditedAt.
- Read-only `snapshot(cdeust/zetetic-team-subagents,218,e220b510...)` completed
  against GitHub: three authenticated feedback nodes, native Codex author.

Before integration the two new workflow contracts failed: missing authenticated
collector and skipped independent bot workflow review. After integration the
focused suite passed 110 tests. Adversarial cases cover public/forged actors,
another editor rewriting a native comment, missing editor metadata, mismatched
GraphQL identities, head moves and green/red workflow bot commits.
