# PR bot repair and merge checks

Edit `templates/ci/pipeline.yml` and `templates/ci/pipeline-after-merge.yml`, then
run `bash scripts/setup.sh render-ci .`. The renderer copies both templates with
their Git blob identifiers and preserves the repository's `ci.json`.

The five test categories, the 90 percent line-coverage gate, and the three bare
runner environments remain the existing CI contract. The common Claude CLI pin
is 2.1.306, measured passing in [claude-mods PR45's unit job](https://github.com/cdeust/claude-mods/actions/runs/39773059845/job/119805310369).

## Review and repair

The review uses the official [Claude Code review plugin invocation](https://code.claude.com/docs/en/github-actions#run-a-skill).
The action's [allowed_bots input](https://github.com/anthropics/claude-code-action/blob/a5a423f75c251dcbff8a74e99f83b2cb03c72bfa/action.yml)
permits only `claude[bot]` and `chatgpt-codex-connector[bot]` as bot actors. The
existing scoped tool permissions stay unchanged. This does not add a Codex job.

For an eligible human-authored head, Claude reviews and then fixes findings or
failed tests. A Claude-authored head skips duplicate review; it still runs the
fix step if any of the five test jobs did not succeed. When those jobs are all
green, it runs neither action. The guard refuses a checkout that has advanced
beyond the event's head, and a Git diff failure fails the guard.

The repair job and read-only merge gate use `always() && !cancelled()`: normal
test failures still reach repair and the explicit merge gate, but cancelling
the workflow prevents further repair or merge work. GitHub re-evaluates job
conditions during cancellation; `always()` alone keeps a job running
([cancellation reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation)).

The existing bootstrap exception remains: a PR changing
`.github/workflows/pipeline.yml` skips both bot actions. Dependabot remains
outside Claude's review scope. Draft and fork PRs remain ineligible.

## Merge and release

Merge requires the contract and all five test jobs to succeed. Review must
complete successfully; its only permitted skipped-job result is the existing
Dependabot exception. Failure, cancellation, timeout, and missing results block
the merge. A skipped bot step inside a successful review job preserves the
bootstrap and Claude-head behavior described above.

The PR merge job validates eligibility without mutating the PR. A separate
`Pipeline after merge` workflow listens for successful PR Pipeline completion
and calls the same local Pipeline through `workflow_call`. GitHub rejects a
workflow listening to itself; source run40017492191 demonstrated that restriction.
The [reusable-workflow context contract](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#github-context)
preserves the caller's workflow_run event. Its permission union allows the called
jobs to narrow permissions; the caller has no competing concurrency group.

The privileged resolve job rereads the source run and exact required job results,
then rejects drafts, holds, closed unmerged PRs, wrong repositories and changed
heads. It merges synchronously through the protected API with the tested head
SHA. All five test categories and the tag use the returned merge SHA. Human main
pushes retain their existing test path. No administrator bypass or polling is used.

The completion caller must exist on the default branch before workflow_run can
fire. Adding it in a draft PR proves its structure, not post-merge execution.
The first rollout therefore requires the existing protected bootstrap path;
subsequent completion runs can use the new caller.

The tag job depends on all five successful test categories and the contract.
The contract reads JSON root.version, or metadata.version only when root.version
is absent, preserving session-optimizer's historical bundle release version.
TOML uses project.version or package.version. Explicit release_packages declare
independent monorepo tags. Existing tags remain unchanged; missing tags publish
atomically through the existing SSH key path.

## Regression evidence

`tests/test_ci_pr_safety.py` executes the template's shell guards with fixture
Git and GitHub responses. It covers red Claude heads in every category, workflow
bootstrap skips, stale checkout rejection, unsuccessful job states, live PR
holds and eligibility rejection. Resolver tests cover exact API merge arguments
and server rejection. They perform no remote write.
Before the initial change, this suite reported 31 failures and 27 passes.
The two added cancellation-source regressions failed before the cancellation
veto was added and pass afterward; hosted cancellation remains a runtime
acceptance check.

The focused post-change suite includes the existing template, contract, and
coverage tests. Actionlint checks the template and rendered workflow; the
render-ci suite checks byte parity, idempotency, and preservation of `ci.json`.
These checks verify workflow behavior and structure. Hosted action execution and
native bot review remain the publication acceptance checks.

## Cargo compilation cache

A root `Cargo.lock` enables caching only in unit, regression and E2E. Keys
separate operating system, architecture, job, toolchain, Cargo configuration,
`ci.json` and lockfile. The fallback retains every boundary except the lockfile,
so Cargo can reuse unchanged dependencies after a dependency update. Cached
paths are `target` and Cargo's registry index, package archives and Git database,
following the [Cargo CI guidance](https://doc.rust-lang.org/cargo/guide/cargo-home.html#caching-the-cargo-home-in-ci).
Environment and installation still run without this cache.

The unit job uses the pinned cache action's separate
[restore/save operations](https://github.com/actions/cache/blob/55cc8345863c7cc4c66a329aec7e433d2d1c52a9/save/README.md):
a successful unit command saves its build before the independent 90 percent
coverage gate. Failed commands do not save; coverage failures remain failures.
Regression and E2E use the ordinary successful-job cache save. This change enables
reuse; it makes no claim about warm-run duration before a hosted measurement.

The template regression uses the `actionlint` executable installed alongside
`PYTHON_BIN` by hash-locked `actionlint-py==1.7.12.25`. Its
[build configuration](https://github.com/Mateusz-Grzelinski/actionlint-py/blob/v1.7.12.25/_custom_build/checksums.cfg)
pins official `rhysd/actionlint` 1.7.12 release archives and their SHA256 hashes.
This removes the assumption that a fresh regression runner already has `uvx`
or a global linter; a missing binary still fails the check.
