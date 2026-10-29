# One CI for every repository, run by the Claude bot

Date: 2026-10-22. Owner: cdeust. Status: draft for the owner's approval.

## Intent

Every pull request on the owner's eight repositories goes through the same
seven steps, in this order, and nothing else:

1. unit tests
2. non-regression tests
3. end-to-end tests
4. environment tests
5. installation tests
6. the Claude bot reviews the PR and pushes its corrections
7. squash merge, then a release tag from main

The owner's words: "Claude bot → regression tests → installation tests →
merge and that's all"; "a repo must have enough test coverage"; "a plugin
works if it installs the same way on Windows, Linux and macOS without
third-party dependencies or manual setup". The bot owns the pull requests
end to end. No human, and no local agent, reviews, rebases, fixes or merges
a PR.

The repositories: zetetic-team-subagents, Cortex, session-optimizer,
claude-mods, cortex-viz, ai-architect-mcp-spec, ai-architect-mcp-codebase,
cortex-know-when-to-stop-training-model (all under github.com/cdeust).

## Goals

- One generic `ci.yml`, identical in shape across the eight repositories.
  Each repository owns a full copy; nothing is called from another
  repository at run time. (Owner: "a repo has its CI, except it comes from a
  generic CI.")
- A PR merges only when the five test steps are green on the commit the bot
  last pushed, with no human step.
- The pipeline exposes a product that does not install cleanly; it never
  hides it.

## Non-goals

- Keeping any other PR check. CodeQL, Scorecard, shellcheck, fuzz, identity,
  DCO, marketplace-pins, supply-chain audit, rebundle and sync workflows stop
  running on pull requests. Scheduled or tag-triggered workflows that do not
  touch PRs are out of scope of this design; they are neither kept nor
  removed by it.
- Per-repository exceptions in the pipeline. A repository that lacks a step
  is red until it has the step.

## Anti-goals

- A step that passes when it has nothing to run. An empty command is a
  failure. (Owner: "No, I disagree: a repo must have enough coverage.")
- A merge that skips the re-run after the bot's push. (Owner: "the five
  tests must run again without a break before the merge".)
- A local agent that reviews, fixes or merges. That is the bot's job only.

## Constraints

- The bot is `anthropics/claude-code-action`, used as its documentation
  describes it (https://code.claude.com/docs/en/github-actions). The review
  is the `code-review` plugin from the `claude-code-plugins` marketplace,
  installed through the action's `plugin_marketplaces` / `plugins` inputs
  and invoked as `/code-review:code-review --comment`. Authentication is the
  repository secret `CLAUDE_CODE_OAUTH_TOKEN`, already set on all eight
  repositories. Dependabot PRs need `allowed_bots: "dependabot[bot]"` (the
  action rejects bot actors otherwise; measured on cortex-viz PR #185).
- Actions are pinned by commit SHA.
- Installation and environment steps run on a bare runner for each of
  `ubuntu-latest`, `macos-latest`, `windows-latest`. "Bare" means: what the
  GitHub runner image ships, plus the Claude Code CLI installed by the
  pipeline at a pinned version. Nothing else is installed by the pipeline.
  If the product needs `brew`, `apt`, `pnpm`, a Rust toolchain, Node, jq,
  Git Bash or PostgreSQL to be installed by hand, its installation step is
  red on that OS.
- Coverage threshold: 90 % of lines, enforced in the unit step, same number
  for the eight repositories.
- Mutation testing, where a repository runs it, is scoped to the files the
  pull request changes (owner, 2026-10-22: "le mutation testing doit se
  limiter aux changements de la PR, pas à une passe globale"). No whole-tree
  mutation pass runs in the pipeline; the plugin's `tools/mutation_check.sh`
  already works on changed files only.
- Branch protection on main requires the pipeline's `merge` check and
  nothing else, identically on the eight repositories (decision 3 below).
  Auto-merge and delete-branch-on-merge are on everywhere (done
  2026-10-21).
- Dependabot pull requests are outside the bot's scope: they merge on
  green tests without review (decision 5 below).

## The pipeline, as decided

### Repository contract: `ci.json`

Each repository carries `ci.json` at its root with exactly these keys, each
a non-empty shell command (run with `bash` on every OS; Git Bash on
Windows):

```json
{
  "unit": "...",
  "regression": "...",
  "e2e": "...",
  "environment": "...",
  "install": "..."
}
```

`unit` must produce a coverage report the pipeline can read (Cobertura
XML at `coverage.xml`, the format every stack here can emit: coverage.py,
cargo-llvm-cov, vitest/istanbul). The pipeline fails the step when line
coverage is under 90 %.

`environment` and `install` receive `CI_OS` (`linux`, `macos`, `windows`)
and `CI_WORK` (an empty scratch directory) and must work on the three.

A missing key, an empty command, or a missing `ci.json` fails the pipeline
before any test runs.

### `ci.yml`, generated from one template

The template lives in zetetic-team-subagents next to the other files its
`scripts/setup.sh` already renders for host repositories (builder's choice
of exact path). A `render-ci` command writes `.github/workflows/ci.yml`
into a target repository; the output carries a header line with the
template version so drift is visible. The rendered file has no `uses:` of a
reusable workflow and no reference back to the template repository.

Triggers: `pull_request` (opened, synchronize, reopened, ready_for_review)
and `push` to `main` (for the tag).

Jobs, in dependency order:

1. `contract`: validates `ci.json` (five non-empty keys). Everything else
   `needs` it.
2. `unit` (ubuntu): runs `unit`, reads `coverage.xml`, fails under 90 %.
3. `regression` (ubuntu, needs unit).
4. `e2e` (ubuntu, needs regression).
5. `environment` (matrix of the three OS, needs e2e): installs the Claude
   Code CLI at a pinned version, runs `environment`.
6. `install` (matrix of the three OS, needs environment): fresh scratch
   `HOME`/`CLAUDE_CONFIG_DIR`, installs the CLI, runs `install`.
7. `review` (needs install, runs whether install passed or failed, only on
   `pull_request`, same-repo head, not a draft, not when the head commit
   author is the bot): the bot.
8. `merge` (needs review, only when jobs 2 to 6 all succeeded on this
   commit): `gh pr merge --auto --squash`.
9. `tag` (on push to main only): tags `vX.Y.Z` from the version file the
   repository already uses (plugin.json / pyproject / Cargo.toml /
   package.json) when that tag does not exist yet. Existing tag-triggered
   release workflows keep working from that tag.

### The bot step

Two `claude-code-action` invocations in the `review` job, both with the
OAuth token and `allowed_bots`:

1. Review: the documented `code-review` plugin invocation with
   `--comment`, read-only. Amended 2026-10-29: with
   `--allowedTools "mcp__github_inline_comment__create_inline_comment"` alone
   the skill launched none of its subagents and still posted "No issues
   found" (PR #207, 3 turns in 9 s). Its tools are now the ones its procedure
   uses (subagents, `gh pr diff`/`view`/`comment`, `gh issue`, `gh search`),
   reading tools (Read, Glob, Grep, `gh run view`, `git diff`/`log`/`show`)
   and the test runners (`python3 -m pytest`, `pytest`, `cargo test`,
   `npm test`), nothing that edits. The prompt names the head SHA, requires
   the whole diff, the changed files, the tests and the run's test logs
   before a verdict, and a failed review names its error class
   (`docs/verification/review-bot-tools-20261029.md`).
2. Fix: a prompt that gives the bot the PR number, the branch, and the
   conclusion and log URLs of jobs 2 to 6, and tells it to apply every
   review finding and every test failure on the branch, run the touched
   tests, commit and push to the branch, and change nothing when there is
   nothing to fix. Tools: edit/read/grep tools plus `Bash(git:*)`,
   `Bash(gh:*)`, and the repository's test runners (python3, pytest, uv,
   npm, npx, pnpm, cargo, bash). Checkout with `fetch-depth: 0` on the PR
   head (same-repo PRs only, as in the action's own
   `examples/ci-failure-auto-fix.yml`). Amended 2026-10-29: Fix runs only
   when a test job of the run (`contract` and the five categories, all in
   `review`'s `needs`) has the result `failure`, the run is not cancelled
   and no earlier step failed; the bootstrap guard (workflow PR not authored
   by the owner) still skips it. On run 40862677865 every test job was
   green, Fix still applied a review finding and pushed e1dcc25, and that
   push cancelled the run. Review findings on a green run stay as comments
   (`docs/verification/native-review-tools-fix-guard-20261029.md`).

A push by the bot is a `synchronize` event: the pipeline runs again from
`contract`. On that run the head commit's author is the bot, so `review`
does not run again (loop guard); `merge` arms auto-merge when jobs 2 to 6
are green. Auto-merge then merges when the required check is green.

The bot cannot edit files under `.github/workflows` (the App token has no
`workflows` permission), so workflow changes are human or agent commits
and get no bot review.

The owner's rule: the five tests run again on the bot's commit, and only a
green run merges.

### Branch protection

Required status check on `main`: the `merge` job's check name. No required
reviewers, no other required checks. Auto-merge and delete-branch-on-merge
on (already true on the eight repositories).

## Known red cells on day one

From the repositories' own files (inventory of 2026-10-22). The pipeline
reports them; the bot or the owner fixes the product, not the pipeline.
The table is under "Decisions from the review", corrected by decision 6.

## Left to the builder

- Exact template path and `render-ci` command inside zetetic-team-
  subagents' existing setup tooling.
- The `ci.json` content per repository, derived from the inventory (unit,
  regression and e2e commands exist in most repositories; environment and
  install must be written where missing, as tests in the product).
- The coverage reader (one small script in the template, or a pinned
  action) and the Cobertura producer flag per stack.
- The exact `if:` expressions for the loop guard and the merge condition.
- The pinned Claude Code CLI version for the install matrix (Cortex pins
  2.1.296 today).
- Removal of the superseded PR-triggered workflows per repository, in the
  same PR that adds the generated `ci.yml`.
- The `claude.yml` mention workflow (documented example) stays as a
  separate file; it is not part of the PR pipeline.

## Out of scope, named so nobody builds it

- Security review in CI (owner chose code-review only, 2026-10-21).
- Any local review, rebase, fix or merge of PRs by agents on the owner's
  workstation.

## Decisions from the review (PR #181, 2026-10-22)

The questions came from the builder check, verified against the live
repository settings and the action's source at a5a423f. The Claude bot
settled them in its review of this pull request; the owner settled the
credential.

1. **Credential for merge and tag.** A merge or tag made with the workflow
   `GITHUB_TOKEN` starts no other workflow, so the `tag` job and the
   tag-triggered releases would never run. Decision (owner): the `merge`
   and `tag` jobs use the same mechanism as Cortex's release gate
   (ci.yml:1175-1201): checkout with `ssh-key: ${{ secrets.RELEASE_TAG_SSH_KEY }}`,
   the private half of the write-enabled deploy key
   `cortex-release-tag (release-gate)`, and push the tag over SSH. The job
   skips cleanly, with a summary line, when the secret is absent. A
   GitHub deploy key belongs to one repository, so each of the seven
   other repositories got its own write-enabled deploy key
   `<repo>-release-tag (release-gate)` and the secret
   `RELEASE_TAG_SSH_KEY` holding its private half (done 2026-10-22,
   verified with `gh api repos/<r>/keys` and `gh secret list`).
2. **Pull requests that change `ci.yml` get no bot review.** The action
   skips when the workflow differs from the one on `main`
   (`workflow_not_found_on_default_branch`). Decision: accepted. The eight
   bootstrap PRs and every template bump merge on green tests and carry no
   bot review; the pipeline says so in the run summary. No workaround of
   the action's default-branch check.
3. **Branch protection.** Identical on the eight repositories: the `merge`
   check required, no required reviews, no conversation resolution, no
   up-to-date-branch requirement, `enforce_admins` off. Set before the
   first auto-merge is armed; without protection, auto-merge merges at
   once, before the re-run on the bot's commit. Today four repositories
   have none, three require conversation resolution, two require an
   up-to-date branch.
4. **Failed or skipped `review`.** A failed `review` blocks `merge`. A
   skipped `review` does not, only when the skip is by design: draft, loop
   guard (bot-authored head), bot actor, `ci.yml` change. `merge` is
   written `if: always() && needs.review.result != 'failure' && …` with
   each skip reason explicit.
   Corrected 2026-10-22 after claude-mods #38 and session-optimizer #73
   auto-merged on a red pipeline: when that `if:` was not met the job was
   skipped, and GitHub treats a skipped required check as satisfied.
   `merge` now runs `if: always() && github.event_name == 'pull_request'
   && !github.event.pull_request.draft && github.event.pull_request.head
   .repo.full_name == github.repository`, checks out nothing, and its first
   step fails explicitly, naming each of jobs 2 to 6 that did not succeed
   or a failed `review`, so the required check is red, never absent.
5. **Dependabot.** Out of the bot's scope: Dependabot PRs merge on green
   tests without review. No Dependabot secret is created (it would widen
   the attack surface, and the code-review command skips automated PRs
   anyway). Stated in the Intent section's scope.
6. **"Bare runner".** The definition stays: the GitHub runner image plus
   the pinned Claude Code CLI. jq, Node, `gh`, curl and Git Bash are not
   red cells. The stricter claim, no third-party dependency, is checked by
   the repository's own `install` command, for example by running with
   `PATH` stripped to the essentials.
7. **Coverage in multi-stack repositories.** 90 % of what `unit` reports,
   as one merged Cobertura `coverage.xml`. No per-language gate. Shell code
   is excluded unless the repository has shell tests.
8. **One review per human push.** The review guard is keyed on the head
   SHA, not on "Claude already commented". A bot-authored head commit
   still skips the review (loop guard).
9. **Install and tag source.** The Claude GitHub App must be installed on
   ai-architect-mcp-codebase before its bootstrap. For cortex-viz,
   `plugin.json` is the single version source; `contract` fails when the
   other version files disagree.

### Day-one red cells, corrected by decision 6

| Repository | Missing today |
|---|---|
| claude-mods | no CI at all: regression, e2e, environment, install, coverage |
| cortex-know-when-to-stop-training-model | regression, e2e, environment, install; pytest not run in CI |
| session-optimizer | e2e, install |
| cortex-viz | e2e, environment, install; views need Cortex's PostgreSQL |
| ai-architect-mcp-spec | install |
| zetetic-team-subagents | install |
| ai-architect-mcp-codebase | the plugin refuses Windows (bin/ensure-binary.sh:276-281) |
| Cortex | Windows leg of install is new |

Coverage under 90 % is a red cell wherever it applies (Cortex 82 %,
ai-architect-mcp-codebase 80 %, zetetic-team-subagents 80 % today).

## Owner actions, outside the pipeline's reach

Each is repository administration the pipeline cannot do for itself; the
agent's own attempts were refused (deploy key: "key is already in use";
branch protection: classifier `[CI Bypass]`).

- Add the public half of Cortex's deploy key `cortex-release-tag
  (release-gate)` (id 159668310) as a write-enabled deploy key on the
  seven other repositories, and the secret `RELEASE_TAG_SSH_KEY` with the
  same private key.
- Apply the branch protection of decision 3 on the eight repositories.
- Install the Claude GitHub App on ai-architect-mcp-codebase.
