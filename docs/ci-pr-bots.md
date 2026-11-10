# PR bot repair and merge checks

For native Codex plus Claude reviews, use the explicit
[`--native-review` profile](ci-native-reviews.md). The behavior below describes
the default renderer.

Edit `templates/ci/pipeline.yml` and `templates/ci/pipeline-after-merge.yml`, then
run `bash scripts/setup.sh render-ci .`. The renderer copies both templates under a fixed
header without a hash and preserves the repository's `ci.json`.
It also delivers the review the resolver waits for, from `templates/ci/review/`:
`claude-review.yml`, `scripts/ci_review_budget.py`, the `/review-pr` command and its reviewers.

The five test categories, the 90 percent line-coverage gate, and the three bare
runner environments remain the existing CI contract. The common Claude CLI pin
is 2.1.306, measured passing in [claude-mods PR45's unit job](https://github.com/cdeust/claude-mods/actions/runs/39773059845/job/119805310369).

## Review

The default profile follows Cortex, the source of truth for the CI of the eight
repositories (owner direction 2026-11-09). The Pipeline carries no review job. The
review is its own workflow, `.github/workflows/claude-review.yml` (`PR Review`): at
most three automatic reviews per pull request (`scripts/ci_review_budget.py`), each
ending with one line, `Verdict: approve` or `Verdict: block`. Draft, fork and
Dependabot-triggered runs are not reviewed. The Pipeline no longer repairs a red head
itself; a repair is asked for with an `@claude` comment (`.github/workflows/claude.yml`).

The read-only merge aggregate uses `always() && !cancelled()`: test failures still
reach it, and cancelling the workflow stops it. GitHub re-evaluates job conditions
during cancellation; `always()` alone keeps a job running
([cancellation reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation)).

## Merge and release

The `merge` job requires the contract and the five test jobs to succeed, and reads
nothing else. It merges nothing and arms no auto-merge. The resolver merges a head
when its Pipeline succeeded and the latest Claude verdict bound to a review run of
that same head approves; a verdict of an older head, a missing verdict or `block`
holds the merge. A Dependabot pull request made of one GitHub-signed commit, whose
declared updates are all minor or patch and whose files are dependency manifests or
locks outside `.github/`, merges on green checks without a review. A change to a
workflow file never takes that path.

The PR merge job validates eligibility without mutating the PR. A separate
`Pipeline after merge` workflow listens for the completion of the PR Pipeline and
of the review, which finish in either order, and calls the same local Pipeline through `workflow_call`. GitHub rejects a
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

`tests/test_ci_pr_safety.py` executes the merge aggregate's shell with every
unsuccessful job state. `tests/test_ci_post_merge.py` drives the resolver through
its HTTP boundary: exact merge arguments, server rejection, live PR holds, and a
merge held without an approving verdict of the tested head. The verdict binding,
the low-risk tier, the review wake-up and the issue closer have their own files
(`tests/test_ci_review_dictates_merge.py`, `tests/test_ci_low_risk_tier.py`,
`tests/test_ci_review_wakes_resolver.py`, `tests/test_ci_resolver_closes_issues.py`).
They perform no remote write.
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

Each category explicitly requires !cancelled() and successful results for every
direct dependency. Tag publication explicitly requires contract and all five
categories to succeed. These status functions avoid inheriting a skipped
resolve ancestor on PR/push events while still refusing failed, cancelled or
skipped test prerequisites. Source run40018808255 exposed the implicit skip;
tests/test_ci_job_conditions.py covers the explicit conditions and their refusal
cases. Hosted jobs must actually execute before a green run is accepted.
