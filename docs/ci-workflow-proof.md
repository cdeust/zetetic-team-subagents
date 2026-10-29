# Native merge authorization

Finding: https://github.com/cdeust/cortex-voice/pull/5#discussion_r4408352195.
A successful Actions run authenticates its status, but a PR writer can replace
`pipeline.yml` and reproduce all expected successful names. The native resolver
now authenticates the executed workflow definition before issuing a merge PUT.

GitHub's GraphQL `WorkflowRun.file` returns `WorkflowRunFile`, documented as
"An executed workflow file for a workflow run." The trusted resolver queries
the live REST run's `node_id`, binds the returned database ID and attempt to
that same run, and validates the file's repository, exact workflow path and
immutable SHA URL. It reads bytes at that server-reported commit, rather
than assuming PR-head or current merge-ref contents identify the executed
definition. No candidate program is imported or executed; file bytes are API data.

The bytes must equal either the installed main workflow definition or
`cdeust/zetetic-team-subagents:main:templates/ci/native/generated/pipeline.yml`.
Both authorities are protected main branches. The shared source export permits
autonomous renderer upgrades and native installation without trusting actors,
owner PRs, rerun initiators or PR-controlled job names. This compares definitions,
never PR base/head commits with current main for merge eligibility. Existing job
checks, PR holds, tested-head merge preconditions and main protection stay enforced.
No new tokens, token artifacts, permissions, external services, or paid-plan
features are introduced. Missing, malformed or error-bearing API results fail closed.

`templates/ci/native/pipeline.yml` owns the jobs. `scripts/lib/render_ci.py` splits
the direct and completion workflows. `tools/ci_workflow_proof.py` is embedded
byte-for-byte in the resolver. Refresh the published definition from the renderer's
`artifacts(native_review=True)` output after changing the template; a test enforces
exact equality. A consumer upgrade is eligible after that source definition reaches
protected main. If a proposed generated upgrade no longer matches either trusted definition, regenerate it from protected source; this authorizes a definition and does not impose PR-base freshness. The legacy profile is unchanged.

Live verification on 2026-10-29: affected Pipeline run `40810523302`, REST node
`WFR_kwLOS8mW5M8AAAAJgH8qpg`, returned GraphQL database ID `40810523302`, attempt `1`,
repository `cdeust/cortex-voice`, and immutable executed file URL
`https://github.com/cdeust/cortex-voice/blob/0c24cf4da7b705276fa1515c8d03df002ea45bd9/.github/workflows/pipeline.yml`.
The live introspected schema and official documentation confirm the field's
executed-file contract. The existing resolver declares Actions read and Contents write (which includes read); no new grant is requested. The shared source is verified public (`private:false`, `visibility:public`), so no access to another private repository is assumed. Hosted GITHUB_TOKEN permission compatibility remains a
post-publication check; local fixtures cannot prove hosted acceptance.

The negative regression first failed with `DID NOT RAISE PostMergeError`, proving
an unauthorized PUT from API-shaped successful run/job fixtures. Tests cover
fake definitions, wrong run/attempt/repository/path, mutable or foreign file URLs,
GraphQL failures, normal code PRs and generated workflow upgrades. All fixture
IDs and SHAs are explicitly synthetic.

Primary source: [GitHub Actions GraphQL schema](https://docs.github.com/en/graphql/reference/actions#workflowrunfile).

The source PR's `Workflow definition API capability` workflow provides the
missing hosted measurement. It uses only Actions/Contents read permissions,
performs no checkout, and uses the exact resolver HTTP transport (AST equality
is tested). It validates its own run/attempt and executed-file pointer with
GITHUB_TOKEN, then reads `cdeust/Cortex`'s public pipeline through the same
Contents API. It prints only sanitized identities and a public Git blob hash.
A green hosted result is required before declaring scoped-token compatibility.


Native rendering also exports `scripts/tests/test_ci_workflow_authorization.py`.
The native contract job runs this named stdlib unittest before reading the
configured unit commands. The tests compile the actual generated post-merge
resolver and its embedded proof, then exercise installed/canonical acceptance,
untrusted metadata/definition rejection, the tested-head merge precondition,
and nonzero CLI/no-output failure signals. Source renderer tests run both
schedule profiles with site packages disabled and prove that removing the
actual authorization call makes the exported contracts fail.
