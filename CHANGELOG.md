# Changelog

All notable changes to this project will be documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **§14 Boy-Scout Rule (mandatory, all stakes)** in `rules/coding-standards.md` — any defect *seen* in material a change touches (fmt, lint, dead code, weak/flaky test, broken doc link, size-cap violation) must be fixed in the same PR; bypassing it (temp-dir dodges, skip flags, narrowed globs, or an un-issued "pre-existing"/"unrelated"/"untouched by me" classification) means the deliverable is refused without review. Only a defect genuinely outside the change's blast radius may be deferred, and only as a filed issue whose number is cited in the report. Wired as a Boy-scout gate into `engineer`, `refactorer`, `test-engineer`, `frontend-engineer`, `devops-engineer`, `dba`, `mlops`, `data-scientist`, and `latex-engineer`, and as a blocking Move 0 (ledger reconciliation + seen-defect refusal check) in `code-reviewer` — a diff or report with an un-issued rationalization is REFUSED, not requested-changes. `commands/git/pr.md`'s Completion Ledger template gained an H7 row for the check. Issued after three same-day agent rationalizations ("unrelated failure" on a 9/10 test tally, "pre-existing flake," and "pre-existing fmt debt untouched by me" bypassed via temp-dir gymnastics instead of running the formatter) were caught re-scoping problems instead of solving them.

## [2.28.1] — CI audit gate fix + subagent alignment

### Fixed
- **`agent-definition-auditor.sh` now actually gates in CI** — the script's default `ROOT` was a hardcoded personal absolute path that didn't exist on the CI runner, so the glob silently matched 0 files and the whole audit (F1-F9, FD, B1-B3, G1-G3, P1) passed vacuously. `ROOT` now resolves relative to the script's own location, and a 0-match glob fails explicitly (exit 2) instead of reporting an empty pass. All 97 genius agents also gained an explicit `tools:` frontmatter field (previously scoped only via the plugin manifest's blanket "All tools" grant), bringing F8/F9 from 22/119 to 119/119 passing.
- **26 genius agent descriptions repaired** — 4 agents (`deming`, `fisher`, `leguin`, `ranganathan`) shipped with frontmatter `description` truncated mid-sentence by a JSON double-encoding bug (e.g. `"W."`); a further 10 had the same corruption undetected until a new quality gate (check FD: description ≥ 40 chars, no broken escape artifacts) was added to the auditor, and 16 more had valid-but-terse descriptions. Since `description` is the spawn/routing criterion, corrupted values made these agents unroutable; `rules/agent-routing-table.md` was regenerated so the fix reaches routing consumers.
- Orchestrator now validates a subagent's result against its artifact contract before forwarding it downstream, and isolates a failed subtask so it does not invalidate already-validated independent results — encoded as new Move 6 steps and refusal conditions.
- Encoded the anti-passive-waiting lesson (long-running work is foreground-blocking or terminate-and-handoff, never a sleep/poll loop on a background monitor) as binding §8c in the shared memory contract.

## [2.27.0] — git-historian agent + get_impact drift fix

### Added
- **git-historian** team agent — regression provenance and abandoned-approach recovery: traces when a behavior changed, which commit introduced it, and surfaces approaches tried-and-reverted so a session doesn't re-walk a dead end.

### Changed
- Registered the `cortex-viz` memory scope in the central registry so cross-agent recall resolves it.

### Fixed
- Corrected `get_impact` drift in `rules/agent-reference/codebase-intelligence.md` — the doc over-promised the tool's blast-radius (it returns one reverse-edge hop, not transitive/test-aware); wording now matches the implementation.

## [2.26.0] — zetetic spine: evidence directionality (source-before-code)

### Changed

- **Spine beat 2 (`evidence/sources`) now enforces the *direction* of evidence**,
  across all 117 agents (team + genius) via the single generator
  `scripts/generate-spine.py` and its elaboration
  `rules/agent-reference/zetetic-spine.md`. The prior wording — "every claim traces
  to a source" — was direction-agnostic: it was satisfied equally by rigor (read a
  source, derive the code from it) and by fabrication (write the code, then find a
  resembling paper and attach the citation as post-hoc justification). Scientific
  rigor is *source-first*: start from a factual, verifiable, demonstrable source and
  produce the implementation **from** it. A citation attached after the fact to a
  lookalike paper is fabricated proof, not evidence — even when the citation is real,
  because the code was never derived from it.
- Beat 2 now names three refused failure modes, backed by observed provenance audits
  (invented arXiv ids, fabricated benchmark deltas, constants mislabeled with
  unrelated papers): **retrofitted citation** (added after the code, chosen for
  resemblance), **resemblance ≠ prescription** (a paper *about* your topic is not a
  source for your specific value/equation unless it states it *and* its experimental
  conditions match yours), and **borrowed authority** (a hardcoded constant wearing a
  paper's name with no line the paper actually prescribes). The honesty discriminator
  is the provenance comment written *before* the value plus an explicit
  "engineering-default / hand-tuned" disclaimer when a value is not paper-prescribed —
  never the citation alone.
- No source → "I don't know" and stop is now explicit that this is a **gate failure,
  not a formatting gap to fill later**: do not ship, then justify.

### Notes

- Content-only change to the injected `<zetetic-spine>` blocks; no tool, hook, or
  memory-contract surface changed. `scripts/generate-spine.py --check` is clean
  (idempotent) and all seven release-gate memory suites pass locally.

## [2.24.0] — `simplifier` agent (de-over-engineering) + adversarial-verify simplicity lens

### Added

- **New `simplifier` team agent** (`agents/simplifier.md`). De-over-engineers code
  that already works and breaks no hard rule but carries more complexity than its
  problem requires — premature abstraction, needless indirection, speculative
  generality, premature optimization, and drifted duplication. Distinct trigger from
  `refactorer`: refactorer fixes *hard-rule violations*; simplifier removes
  *superfluous complexity that violates no hard rule* (already-functional,
  already-compliant code never invokes refactorer, so over-engineering needs its own
  trigger — folding both into one agent would be an SRP violation in agent design).
  Behavior-preserving (tests pass before and after, one simplification per commit),
  stakes-calibrated, and language-/project-agnostic (idiom-mapping across Python,
  TypeScript, Go, Rust, Java, Swift). Its over-engineering heuristics are an **open,
  non-exhaustive catalog** (YAGNI, rule-of-three, needless indirection, premature
  optimization, speculative generality, drifted duplication, plus KISS, Gall's Law,
  Ousterhout shallow modules, dead code, boolean blindness, …) — each removal must
  name and source its principle per the zetetic §8 standard. New `simplifier` memory
  scope (`memory/scope-registry.json`).
- **A2 / CR-4 — adversarial-verify pre-verdict workflow** now carries a **fifth,
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
  *definition files* the README/marketplace count — `memory-writer` is a scribe that
  owns no scope. A new footnote in the doc records the distinction.

### Tests

- `tools/tests/adversarial-verify/core.test.mjs` updated for the five-lens core
  (lens count, lens-keys ordering, distinct-agentType count, five-element fixtures).
  13/13 deterministic synthesis-core tests pass.

## [2.23.0] — CAP-2 reviewer-prefs, history seeding, and doc/count refresh

### Added

- **CAP-2 — adapt to a demanding team lead.** New `reviewer-prefs` memory scope
  (`memory/scope-registry.json`) holding a lead's standing review preferences.
  Owners are the lead (`_user`) and the orchestrator/curator; the reviewed agents
  (`engineer`, `refactorer`, `code-reviewer`) are readers only, so an agent cannot
  invent its own prefs. The three agents read the scope at the top of their workflow
  with a fixed precedence — a `coding-standards.md` blocking rule always outranks a
  preference — and a graceful fallback when the scope is absent.
- **`tools/seed-reviewer-prefs.sh`** — bootstraps a lead's prefs from evidence of how
  they already work (their `gh` review comments + merged PRs), emitting a
  provenance-tagged `status: inferred` draft. It presents raw evidence only;
  abstracting it into confirmed preferences is the lead/orchestrator's judgment step
  (§9 — no faked judgment). Injection-safe, owner-only writes, deterministic exit
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

## [2.22.0] — mutation-test suites for the gate cores + gate-integrity fix

### Added

- In-process pytest suites for `manifest_gate.py` (90.6% mutation score) and
  `semantic_layer.py` (97.4%), wiring both critical zones into the mutation policy.
  `acceptance_gate.py` mutation coverage at 77.6% (residual = documented equivalents).

### Fixed

- `.craftsmanship.conf` size-gate scoping: a test suite had set `FILE_MAX=2000`
  globally, weakening the production 500-line gate. Now test-scoped
  (`TEST_FILE_MAX`/`TEST_FILE_RE`); production stays `FILE_MAX=500`.
- Routing table regenerated to include the `memory-writer` agent.

## [2.21.0] — mechanical craftsmanship enforcement + hook-layer correctness

### Added

- **Craftsmanship checker** (`tools/craftsmanship-checker.sh` + `tools/lib/craftsmanship-detectors.sh`).
  Mechanically enforces `coding-standards.md` §4 size limits and select structural
  rules. `FILE_TOO_LONG` (>500 lines) blocks; function/class/parameter/nesting block
  for recognized languages; grab-bag module names and layer-direction advise.
  Judgment rules (SRP/OCP/LSP/ISP, rule-of-three, dead-code) are deliberately NOT
  mechanized — a hook that fakes a verdict it cannot reach just trains you to ignore
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
  integration in the acceptance gate is a tracked follow-up — an inert draft was not
  shipped (no current caller, per §9).
- The craftsmanship CI gate is a ratchet: newly-added files must fully comply; the
  legacy tree's pre-existing §4 debt (e.g. `scripts/setup.sh`) is surfaced
  informationally, not blocked, until refactored.

## [2.20.0] — autonomous build loop + self-hosted knowledge ingestion

### Added

- **Closed-loop autonomous build** (`.claude/workflows/autonomous-build-loop.js`).
  Drives a build task to a candidate on an isolated iteration branch:
  refine → plan → verify-plan → orchestrator build → best-effort in-loop
  acceptance checks → iterate until green or the budget is spent. Repo-generic —
  `repoPath`, `gateRunner`, and an optional base `gateConfig` are inputs, so the
  loop runs from any working directory against a repo that need not contain this
  tooling. It drafts and converges a candidate; it does not self-certify.
- **Deterministic acceptance gate** (`tools/acceptance_gate.py`,
  `tools/acceptance-gate.sh`). Runs configured *command* gates and aggregates
  their exit codes — a gate passes iff its command exits 0, never a model grading
  its own output (Huang et al., arXiv:2310.01798). Gates any repo via `--root`,
  evaluates the committed tip via `--diff-base/--diff-head` in a throwaway
  worktree, rejects an empty diff, and fails closed. Unit-tested under
  `tools/tests/acceptance-gate/` (incl. external-repo-from-a-foreign-cwd and
  fail-closed cases).
- **Real-exec Stop-hook gate** (`hooks/stop-acceptance-gate.py`) — the build
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
  `superseded` states. Never writes Cortex itself — the agent owns the write and
  passes back the `cortex_id` as a pointer.
- **Manifest-membership gate** (`tools/manifest_gate.py`, `tools/manifest-gate.sh`,
  tests under `tools/tests/manifest-gate/`). Fail-closed grounding check: every
  fact's `source` must be a URL the web-ingest engine actually fetched this
  session. Complements the semantic layer's presence check with a membership
  check; a pure `stdin → stdout` filter.

### Changed

- **README: broader refresh.** Corrected counts to ground truth — agents
  116 → 117 (a 20th team-role agent, `memory-writer`), skills 63 → 64; documented
  the autonomous build loop and the new knowledge-ingestion / semantic-layer
  subsystems; refreshed the genius-trigger source comment (recounted 2026-06-23).
- **Marketplace manifest** counts refreshed (20 team agents, 64 skills,
  25 commands, 24 logical tools, 17 registered hooks).

### Fixed

- **`web-ingest` follows 308 redirects** and records the final resolved URL.
- **Manifest-gate comments** reworded to satisfy the absolute-claim checker (§8).

## [2.19.1] — fix Release workflow test paths

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

## [2.19.0] — genius corpus inherits the full tool set

### Changed

- **All 97 genius agents drop the explicit `tools:` front-matter line.** Each
  genius now inherits the full session tool set instead of pinning a hardcoded
  allow-list that had drifted from the live tool registry; pinning silently
  starved an agent of any tool the list omitted. Single uniform change — 97
  files, 97 deletions, reasoning sections untouched.
- Validated by a full isolation sweep before release: with the plugin disabled
  and an un-namespaced clone live, all 97 genius agents spawned and responded,
  each confirming file/search tools visible — 97/97, zero failures.

## [2.18.0] — letta-code follow-up: lean genius corpus, compact routing, reflective checkpoints, memory contract hardening

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
- **R3: checkpoint stubs follow the letta summary schema** — goals / file
  references (paths + line ranges) / errors and fixes / current state / next
  steps, ≤500 words, tool outputs clipped to 2K chars, frontmatter
  description retrieval cue. Resume contract: checkpoint + ONE targeted
  recall, never re-reading what the checkpoint summarizes. All 116 agent
  token-budget stubs and the shared token-budget.md doc teach the schema.
- **R4: reflection at WARN, not at HARD.** stop-context-guard.py's WARN
  firing is now a one-time blocking reflection (like letta's compaction
  event): the model spawns the new budgeted **memory-writer** agent (haiku,
  ≤16K context) to persist the semantic checkpoint + cortex:remember entries
  while headroom remains, then resumes the task — the HARD block becomes a
  formality.

### Added

- **R5: mandatory `description:` frontmatter on memory .md files**, enforced
  at the memory-tool.sh chokepoint on create/rethink (instructive error,
  `MEMORY_NO_DESC_CHECK=1` test escape hatch). Contract §4.8.
- **R6: conflict-aware memory verbs** — `rethink <path> <text>
  [expected_sha]` (atomic whole-file rewrite, letta memory_rethink) and
  `sha <path>` (CAS token); `str_replace` gains optional compare-and-swap.
  Contract §3.6b/§3.6c/§4.7; exposed via the memory_extensions MCP tool.
- `agents/memory-writer.md` — single-purpose budgeted reflection scribe.

## [2.17.0] — Lean team agents: core + on-demand reference docs

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

## [2.16.0] — Per-model context thresholds via shared config

### Changed

- **stop-context-guard.py re-vendored from
  [session-optimizer](https://github.com/cdeust/session-optimizer) v1.1.0.**
  Thresholds are now per-model and loaded from
  `~/.claude/ctxguard-thresholds.json` (embedded fallback when the config
  is absent or malformed; first substring match on the lowercased model id
  wins): Fable 5 / Mythos warn 120K hard 160K (2x Opus rates — carrying
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

- **`hooks/ctxguard-thresholds.json`** — vendored copy of the shared
  threshold config. `session-start.sh` seeds it to
  `~/.claude/ctxguard-thresholds.json` when absent (idempotent — never
  overwrites user edits, so tuned thresholds survive plugin updates).

## [2.15.0] — Complete the plugin hook manifest

### Fixed

- **Missing hooks in the plugin manifest.** `.claude-plugin/plugin.json`
  had drifted from `hooks/hooks.json`: the inline `hooks` block omitted
  three hooks that the canonical wiring defines, so they never registered
  when the plugin loaded — `pre-tool-secret-shield.py` (PreToolUse),
  `stop-context-guard.py` (Stop, the context-budget guard from
  [session-optimizer](https://github.com/cdeust/session-optimizer)), and
  `session-end-memory-drain.sh` (Stop). The manifest now mirrors
  `hooks/hooks.json` exactly (17 hook commands). The Stop block fires all
  three lifecycle hooks; PreToolUse re-includes the secret shield.

### Changed

- Marketplace entry hook count corrected (16 → 17).

## [2.14.0] — Public-readiness baseline

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

## [2.13.1] — Tier-1 visibility + memory MCP + PII scanner

### Added

- **Memory MCP.** Local replica of Anthropic's managed-agent
  `memory_20250818` tool with scope-based ACL, queue isolation, and
  full MCP wire compatibility. 241 tests passing across functional, ACL,
  concurrency, stale-lock, MCP, and PII suites.
- **PII / secret scrubbing on memory write path** (contract §7.2).
- **`pre-tool-secret-shield` hook** — blocks any agent from reading
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
