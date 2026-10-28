# Native PR review configuration

Use the opt-in renderer to install native Codex reviews alongside the official
Anthropic review action:

```bash
bash scripts/setup.sh render-ci /path/to/repository --native-review --dry-run
bash scripts/setup.sh render-ci /path/to/repository --native-review
```

The default invocation keeps the legacy Claude review/fix pipeline byte for byte.
The native profile replaces its review and merge jobs with the Cortex native
Codex readers and protected completion resolver. It preserves the common test
jobs and tag publication. Native environment/install jobs use a private
`.github/claude-cli/package.json` and `package-lock.json`, with Claude Code still
pinned to 2.1.306. [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci) installs
that frozen graph under `.github/claude-cli`, and `GITHUB_PATH` exposes its local
bin directory to later steps. The lock records package integrity for the CLI
and its platform-specific native packages. This replaces the four global npm
installs across direct and post-merge workflows; legacy generation keeps its
existing commands.

Its tag job pins `actions/setup-python` v7.1.0 at
`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`, matching the copied Cortex source and
Spec main `616eb04`; the legacy profile retains v7.0.0. This prevents opting in
from downgrading that consumer's existing action. The renderer delivers the three Pipeline workflows,
`Codex.yml`, `claude-review.yml`, `claude.yml`, the Codex reader scripts and the
Anthropic review command with its five reviewers. Existing `ci.json` and
unrelated files are preserved. Every destination is preflighted; a failed file
replacement rolls back workflows and assets together.

## Account and repository setup

Enable automatic Codex review for the repository in the connected Codex account:
all PRs, every push, exhaustive code review, and automatic security review
alongside code review. `Codex.yml` consumes the authenticated completion summaries;
it does not request another model run. A missing code or security review stays
pending. Native reviews are an account prerequisite, not a GitHub Actions secret.

Install the Claude GitHub app and configure `CLAUDE_CODE_OAUTH_TOKEN`. The pinned
Anthropic action supports this OAuth input. Automatic review uses the official
`pull_request` event for same-repository PRs and grants `id-token: write` for the
native Claude App exchange. It leaves `github_token` unset so publication uses
the App identity. The job checks out `main` with persisted authentication
disabled and reads the PR through GitHub APIs. The pinned action restores
sensitive repository configuration from the base before Claude starts.

[GitHub's secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use)
states that repository writers already have read access to repository secrets.
This flow retains the same-repository and non-draft boundary. Fork PRs do not
receive these secrets. The runner installs subprocess-isolation dependencies
and retains environment scrubbing. `claude.yml` retains owner-authored mention
handling.

Both native Claude invocations request `claude-opus-5-5`, explicitly selected
by the owner on 2026-10-28. The ID is documented in Anthropic's
[Opus5.5 overview](https://platform.claude.com/docs/en/models/opus-5-5/overview).
The official review command and five reviewer files remain verbatim and inherit
the selected model.

Both native Claude invocations pass `--strict-mcp-config`. The
[CLI reference](https://code.claude.com/docs/en/cli-reference) documents that this
limits MCP discovery to explicitly supplied configurations. The pinned action
supplies its GitHub configuration before appending user arguments in
[tag mode](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/modes/tag/index.ts#L192-L204)
and [agent mode](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/modes/agent/index.ts#L112-L122).
This avoids launching application/developer servers from consumer `.mcp.json`
files during CI review. Repository settings, the review command and all five
reviewer definitions remain loaded.

These copied workflows target a `main` default branch and same-repository,
non-draft PRs. Partner contributors need repository branch access for this path;
fork PRs do not receive this privileged automatic review or protected merge.
Owner holds remain effective. Changing code does not clear a hold.

Keep the required GitHub Actions `merge` check and existing security checks on
`main`. Do not add a required Claude check during workflow installation; upstream
App authentication skips workflows that have not reached the default branch.
Verify actual automatic publication after protected installation. Retain existing
admin enforcement.
The merge resolver calls the protected merge API with the tested head SHA and
rechecks the base; it does not bypass branch protection. Existing release-key
setup remains necessary for release tag publication.

Install the workflows on `main` before measuring a fresh normal PR. Acceptance
requires actual code and security summaries from Codex, completed Claude feedback,
and all test jobs green on the same current head. Local rendering does not prove
account authentication or hosted model execution.

## Source and local evidence

The assets and native job blocks originate from
[Cortex commit 8e7375bf](https://github.com/cdeust/Cortex/tree/8e7375bf2edfb33fb9c45809b9af6b428f0f4235).
`templates/ci/native/source.json` records SHA256 digests for nine unchanged assets
and two unchanged native job blocks. The Codex runtime asset and review job
record their original and adapted digests for current-finding resolution:
all finding IDs announced by the current authenticated summary must exist,
and only those findings determine its resolution verdict. Historical threads
remain available without invalidating later reviews. Missing current IDs and
the existing identity, owner-resolution and pagination checks still fail closed.
The reader and completion handler also record their last-editor authentication
adaptation. Summary bodies and their last editor come from the same GitHub
GraphQL node. A pristine comment requires null edit metadata; edited content
requires the original native Bot account, including matching immutable actor IDs.
Newer Bot-authored comments with an untrusted editor block reuse of an older
summary even if the editor removed its marker. Ordinary trusted Bot messages
retain their existing behavior.
The two Claude YAML assets also record
original and adapted digests for `--strict-mcp-config` and the owner-selected model. The automatic review
YAML additionally records its native App correction: the official PR trigger,
OIDC permission and removal of the explicit GitHub token override.
The authored private CLI manifest/lock assets have their own digests. The shared
comment-boundary module is also recorded as an authored asset: its functions
were extracted unchanged from the adapted runtime and reader to satisfy the
Cortex source-size cap. The isolated review job preloads runtime, comment
boundary and reader in that order; their exception type remains shared. All
six command/reviewer files remain verbatim. Provenance comments
in copied code may refer to Cortex's original findings. The review logic obtains
the repository and owner from GitHub context; it contains no fixed Cortex target.

The Claude configuration derives from Anthropic's
[PR review workflow](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude-review.yml)
and [mention workflow](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude.yml),
with the documented base checkout, OAuth authentication and native App
adaptations. Cortex's App attribution investigation is recorded in
`docs/verification/claude-app-attribution-20261028.md` in that repository.

Run `python3 -m pytest -q tests/test_ci_native_renderer.py` for native delivery,
source digests, rollback and destination safety. The default renderer's existing
regressions remain in `tests/test_ci_renderer.py` and
`tools/tests/render-ci/run-tests.sh`.
