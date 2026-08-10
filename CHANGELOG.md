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

## [Unreleased]

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
- **Two test-count claims were not reproducible by any command**: a `tests-288`
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
- **Routine dependency maintenance**: the `github-actions` group bumped to
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
- **Check `FP` in `tools/agent-definition-auditor.sh`**: every
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
- **Rules-change discrimination**: when the withheld gap crosses a commit touching `rules/coding-standards.md`, the report says so explicitly: that is the case where agents are enforcing a superseded standard, as opposed to a docs-only bump not worth interrupting for.
- **`--version` / `--rules-version`**: every agent and hook run can name the plugin build and the rules version it operates under.
- **Compliance reports now stamp their standard**: the generated zetetic-spine (118 agents) requires any rule-compliance verdict to state the rules version it was evaluated under. A verdict read later is uninterpretable without it.
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
- **`tools/redaction-checker.sh`: full mechanical inventory**: three new check groups mirror the Cortex-side expansion (cdeust/Cortex#167): CONTRAST (binary contrasts, negative listing, dramatic fragmentation; redaction §9/§35), SETUP (throat-clearing, faux insight, signposting, rhetorical setups; §27-31), PUFFERY (importance puffery, promotional language, copula avoidance, AI conversation artifacts; §1/§4/§8/§20-22). Suite grows 9 → 13 cases including an FP-guard: technical prose brushing pattern shapes stays silent.

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
- **`orchestrator` agent model: opus → fable**: aligns the plan/dispatch/verify role with Anthropic's **Orchestrator loop** (same webinar: ~96% of Fable-alone quality at ~46% of cost on BrowseComp when Fable coordinates parallel Sonnet workers). Executor-class agents stay on sonnet; the existing tiering already matched the pattern's execution half.

## [2.30.0]: zetetic-gates micro-plugin + 11 problem-shaped skills + directory-policy metadata

### Added
- **`zetetic-gates` micro-plugin** (`plugins/zetetic-gates/`, v1.0.0): the mechanical enforcement gates as a standalone 30-second install with zero agents: pre-commit zetetic + craftsmanship gate hook, `tools/zetetic-checker.sh` (blocks unsourced constants and absolute claims), `tools/craftsmanship-checker.sh` (§4 size limits, `.craftsmanship.conf` tunable), and the credential secret-shield. Registered in `.claude-plugin/marketplace.json` (marketplace 2.29.0 → 2.30.0). Engine files are byte-identical copies of the canonical `tools/` + `hooks/` files (a marketplace plugin only ships files under its own directory); the new CI suite `tools/tests/gates-plugin-sync/run-tests.sh` hard-fails on any drift, so the main plugin's hooks and the micro-plugin cannot diverge silently.
- **11 problem-shaped skills** (`skills/<name>/SKILL.md`) wrapping the 97 genius agents by the category structure of `agents/genius/INDEX.md`: `measurement-discipline`, `estimation`, `causal-audit`, `formal-correctness`, `failure-forensics`, `decision-bias-check`, `evidence-synthesis`, `systems-leverage`, `boundary-design`, `structure-discovery`, `problem-reframing`. Each states its problem shape, lists 6–10 best-fit geniuses with one-line triggers, and loads them through the existing `tools/genius-invoker.sh` invoke/route/compose machinery. The README now advertises the skills as the entry point; the 97-agent roster is kept as the reference library. Total SKILL.md frontmatter descriptions: 3.4K chars (well inside the 15K description budget).
- **`PRIVACY.md`**: privacy policy covering both plugins (local-only processing, no telemetry, what hooks read/write), required by the plugin Directory Policy. (#38)

### Fixed
- **`hooks/pre-tool-secret-shield.py` §4.5 nesting violation**: `_strip_write_dest_and_urls` nested 5 levels deep; the transfer-destination drop is extracted into `_drop_transfer_destination` (behavior unchanged, hook-layer suite 96/96).
- **GitHub license detection reported NOASSERTION**: the descriptive preamble, independence statement, and trailing attribution note inside `LICENSE` broke `licensee`, awesome-list license bots, the official marketplace's validate-licenses CI, and anything reading the GitHub license API. `LICENSE` is now the verbatim MIT text; the three explanatory blocks moved to the README license section. (#36)

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
- **`agent-definition-auditor.sh` now actually gates in CI**: the script's default `ROOT` was a hardcoded personal absolute path that didn't exist on the CI runner, so the glob silently matched 0 files and the whole audit (F1-F9, FD, B1-B3, G1-G3, P1) passed vacuously. `ROOT` now resolves relative to the script's own location, and a 0-match glob fails explicitly (exit 2) instead of reporting an empty pass. All 97 genius agents also gained an explicit `tools:` frontmatter field (previously scoped only via the plugin manifest's blanket "All tools" grant), bringing F8/F9 from 22/119 to 119/119 passing.
- **26 genius agent descriptions repaired**: 4 agents (`deming`, `fisher`, `leguin`, `ranganathan`) shipped with frontmatter `description` truncated mid-sentence by a JSON double-encoding bug (e.g. `"W."`); a further 10 had the same corruption undetected until a new quality gate (check FD: description ≥ 40 chars, no broken escape artifacts) was added to the auditor, and 16 more had valid-but-terse descriptions. Since `description` is the spawn/routing criterion, corrupted values made these agents unroutable; `rules/agent-routing-table.md` was regenerated so the fix reaches routing consumers.
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
- **R3: checkpoint stubs follow the letta summary schema**: goals / file
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
- **R6: conflict-aware memory verbs**: `rethink <path> <text>
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
- **`pre-tool-secret-shield` hook**: blocks any agent from reading
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
