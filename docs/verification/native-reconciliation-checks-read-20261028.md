# Native reconciliation Checks permission

The native Codex discovery job declares `checks: read` alongside its existing
read permissions. Its GraphQL query reads `CheckRun` fields from the head
commit status rollup. Workflow defaults and other jobs remain unchanged.
The discovery helper and review protocol are unchanged.

GitHub documents the workflow [Checks permission][permissions] and identifies
[`GITHUB_TOKEN` as an installation access token][token]. CLI maintainer Andy
Feller [maps statusCheckRollup to Checks][cli]. GitHub recommends [testing the
actual GraphQL permissions][graphql]; its implicit public-read statement refers
to user access tokens. REST public-resource access does not establish this
GraphQL query's installation-token behavior.

No missing-permission failure was observed on a public runner. This change
makes the read permission explicit; hosted reconciliation remains unverified.
No token, authentication setting or external service was changed.

[permissions]: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idpermissions
[token]: https://docs.github.com/en/actions/concepts/security/github_token
[cli]: https://github.com/cli/cli/discussions/8083
[graphql]: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app#choosing-permissions-for-graphql-api-access

## Local verification

The rendered-workflow permission test fails before the change because the
Checks entry is absent. It requires the existing workflow defaults and a
read-only discovery permission map, without adding Checks to the other job.
The focused test returned `1 failed, 2 deselected` before the asset change.
The affected schedule, native renderer, renderer and resumption files returned
`31 passed in 2.25s` after it. Actionlint accepted all six rendered native
workflows. Ruff check/format, git diff check, and source/craft/prose checks passed.

The reconciliation helper remains SHA256
`013cbb5510abd2999cff40102c12f93fbe95a6f8264295b2422be65a525e0029`.
No hosted query was run for this permission change.
