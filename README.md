<p align="center">
  <img src="assets/banner.svg" alt="Zetetic reasoning for AI agents: sourced evidence, explicit uncertainty, one epistemic standard" width="100%"/>
</p>

<p align="center">
  <a href="https://github.com/cdeust/zetetic-team-subagents/actions/workflows/ci.yml"><img src="https://github.com/cdeust/zetetic-team-subagents/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/suites-28-brightgreen" alt="Test suites">
  <img src="https://img.shields.io/badge/agents-120-8A2BE2" alt="Agents">
  <img src="https://img.shields.io/badge/skills-76-green" alt="Skills">
  <img src="https://img.shields.io/badge/hooks-19_lifecycle-red" alt="Hooks">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"></a>
  <a href="https://www.bestpractices.dev/projects/13847"><img src="https://www.bestpractices.dev/projects/13847/badge" alt="OpenSSF Best Practices"></a>
</p>

> **Cross-platform evidence synthesis for Codex, Gemini CLI, and Claude Code, plus a full Claude-native distribution of 11 problem-shaped skills backed by 97 sourced reasoning patterns.**
> The portable package audits primary sources, counter-evidence, and uncertainty on all three hosts. The full Claude Code package additionally routes skills such as `causal-audit`, `failure-forensics`, and `estimation` across 97 genius agents (plus 23 team-role agents = 120 total), lifecycle hooks, and a pre-commit gate that blocks any floating-point constant with 3+ significant digits unless it carries a `source:` annotation.
> Not a prompt library. A methodology with **commit-time enforcement**.

---

## The system enforcing its own standard

```
$ git commit -m "tune retry backoff"

UNSOURCED   (error)    retry.py:1: # It always works
MAGIC_NUMBER (error)    retry.py:2: DELAY = 2.741592

Profile: strict  (staged mode)
Errors:   2  (blocking)
Warnings: 0  (informational — promoted to errors when profile=strict)
FAILED: 2 blocking violation(s).

BLOCKED: Zetetic violations in staged files.
```

Composite output: lines 1–2 are verbatim from `tools/zetetic-checker.sh --staged`; the closing `BLOCKED:` line is the wrapper from `hooks/pre-commit-zetetic.sh` that returns exit 2 to git. Reproduce on your machine: `echo "DELAY = 2.741592" > /tmp/x.py && cd /tmp && git init -q && git add x.py && ZETETIC_PROFILE=strict bash <repo>/tools/zetetic-checker.sh --staged`.

The commit re-runs once each flagged line carries a `# source:` comment, a benchmark reference, or a measured-on note.

---

## Why this exists

Every AI agent system ships a role prompt. *"You are a senior engineer."* The agent sounds confident. It invents numbers, cites papers it hasn't read, and ships code with conviction inversely proportional to its correctness.

Zetetic Agents are different in one specific way: **they can say "I don't know."**

97 reasoning patterns drawn from primary sources (Dijkstra's correctness discipline, Curie's residual-with-a-carrier method, Hamilton's fault-tolerance protocol, Cochrane's evidence synthesis), routed automatically to your problem by *shape*, not by *field*. Every output is sourced. Every commit is checked. The standard is not a prompt. It is a gate.

---

## The entry point: 11 problem-shaped skills

You don't browse a roster of 97 historical figures. You name the *shape* of your problem. Each skill lists the 6–10 reasoning procedures that fit that shape, with one-line triggers, and loads the best fit on demand:

| Skill | Invoke when |
|---|---|
| [`measurement-discipline`](skills/measurement-discipline/SKILL.md) | the metric improved but you don't trust it; numbers don't add up; nothing actually reads X |
| [`estimation`](skills/estimation/SKILL.md) | decision blocked by "no data"; suspiciously precise number; "is this even feasible?" |
| [`causal-audit`](skills/causal-audit/SKILL.md) | "X causes Y" claimed from correlation; "did the change cause the improvement?" |
| [`formal-correctness`](skills/formal-correctness/SKILL.md) | concurrent/distributed code with no spec; correctness argued by example traces |
| [`failure-forensics`](skills/failure-forensics/SKILL.md) | incident post-mortems; anomalies filtered as noise; undesigned degraded modes |
| [`decision-bias-check`](skills/decision-bias-check/SKILL.md) | high-stakes call on fast intuition; no pre-mortem; metric being gamed |
| [`evidence-synthesis`](skills/evidence-synthesis/SKILL.md) | conflicting studies/benchmarks; "what does the literature actually say?" |
| [`systems-leverage`](skills/systems-leverage/SKILL.md) | local fixes keep failing; recurring org patterns; "where should we intervene?" |
| [`boundary-design`](skills/boundary-design/SKILL.md) | build-vs-buy; module/team/API boundary placement; leaky abstractions |
| [`structure-discovery`](skills/structure-discovery/SKILL.md) | hidden pattern suspected; reverse-engineering; classification with gaps |
| [`problem-reframing`](skills/problem-reframing/SKILL.md) | debate in circles; false binary; a trade-off being denied; "we're stuck" |

Each skill body names the relevant genius agents, when to use each, and how to load them (`tools/genius-invoker.sh invoke <agent> "<problem>"`). The full 97-agent roster stays available as the [reference library](#the-reference-library-97-reasoning-patterns).

---

## What you type → what happens

```
/paper-vs-code-audit arxiv:2401.12345 ./src/
→ Extracts every claim → finds corresponding code → flags mismatches → traceability matrix

/autoresearch-loop "optimize beam search for abstention"
→ Hypothesis → implement → commit → benchmark → keep/revert → iterate until diminishing returns

/deep-research "transformer attention alternatives 2024-2026"
→ Plans search → parallel researchers → synthesizes → verifies citations → writes cited brief + provenance sidecar

/incident-investigation
→ Forensic timeline → three-timescale decomposition → common vs special cause → structural root cause → remediation

/genius route "p99 latency exceeds the sum of profiled components"
→ Routes to the reasoning procedure that fits the problem shape
```

These aren't prompts dressed up as commands. Each is a **multi-step pipeline** that names the procedure used, surfaces blind spots in its output, and refuses to ship if a step fails. See [`docs/EXAMPLES.md`](docs/EXAMPLES.md) for full session transcripts.

---

## Install

### Portable evidence synthesis for Codex and Gemini CLI

The isolated [`zetetic-reasoning`](plugins/zetetic-reasoning/README.md) package
ships one evidence-synthesis skill and eight sourced reasoning references. It
does not install the agent roster, lifecycle hooks or mechanical gates.

```bash
# Codex
codex plugin marketplace add cdeust/zetetic-team-subagents
codex plugin add zetetic-reasoning@zetetic-marketplace

# Gemini CLI
gemini skills install https://github.com/cdeust/zetetic-team-subagents.git \
  --path plugins/zetetic-reasoning/skills/evidence-synthesis
```

### Full Claude Code distribution

```bash
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-team-subagents
```

That's the whole install. The plugin's installer copies agents, skills, hooks, and tools into `~/.claude/`. Manual install + advanced config: [`docs/INSTALL.md`](docs/INSTALL.md).

**Just want the enforcement gates, no agents?** Install the 30-second micro-plugin instead: `claude plugin install zetetic-gates`. It ships the pre-commit zetetic + craftsmanship checkers and the secret-shield, nothing else. See [`plugins/zetetic-gates/`](plugins/zetetic-gates/README.md).

### Staying current, and why a release can fail to reach you

This plugin's product is rule currency, so running a stale copy is not a mild
degradation: agents enforce a **superseded** standard and certify the result.
Session start therefore checks three values and stays silent unless one is off:

| | Meaning | Who fixes it |
|---|---|---|
| `installed` | the build this session loaded | n/a |
| `pinned` | the version the marketplace serves | n/a |
| `released` | the latest published release | n/a |
| **`installed < pinned`** | you have not updated | **you**: run `/plugin` and restart |
| **`pinned < released`** | the release was never delivered | **the marketplace-owning repo**, named in the message |

Check it any time:

```bash
tools/plugin-version-check.sh          # silent when current; names the lag otherwise
tools/plugin-version-check.sh --json   # machine-readable
tools/plugin-version-check.sh --version --rules-version
```

The second row is not hypothetical. On 2026-07-24 the installed plugin ran
v2.29.0 while v2.34.0 was released. Six releases, including §15 and the
redaction gates, reached zero installs, because the version is pinned in a
*different* repository's marketplace manifest and nothing bumped it. No user
action could have fixed that, and nothing reported it. The check is fail-open:
offline, rate-limited, or unreadable metadata prints a `NOTICE` and never
blocks or fails a session.

### Windows prerequisites

Agents, rules, skills, and commands are static Markdown and work natively. The
**hooks** need two things present on Windows:

- **Git Bash**: the `.sh` hooks run through the bash shipped with [Git for Windows](https://git-scm.com/download/win) (`C:\Program Files\Git\bin\bash.exe`). Without it, every shell hook is silently skipped.
- **A working Python 3**: install from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*). The `python3` name in `PATH` is usually the Microsoft Store stub, which is not Python; the Python hooks resolve the interpreter via [`hooks/run-python.sh`](hooks/run-python.sh), preferring the `py -3` launcher. Verify `py -3 --version` works, and disable the Microsoft Store `python`/`python3` *execution aliases* (Settings → Apps → Advanced app settings → App execution aliases) if `python3` shadows your real install.

`setup.sh` probes both and warns if either is missing. Restart Claude Code after changing `PATH`.

---

## What you actually get

| Capability | What it gives you (concretely) |
|---|---|
| **97 documented refusals** | Each genius agent's body documents conditions under which it refuses (when to stop, what to cite, when to hand off). Refusal conditions are intent statements, not enforced contracts. |
| **76 multi-step workflows** | 11 problem-shaped skills route you to the right reasoning procedure; 65 category skills run full pipelines: type one slash command, get a sourced research brief / debugging trace / ADR. Each agent in the chain produces output and declares what it could not verify. |
| **Commit-time gates** | `pre-commit-zetetic.sh` blocks commits with `UNSOURCED` keywords (always/never/obviously) at any profile. `MAGIC_NUMBER` floats (3+ decimals without `source:`) and `TODO_NO_REF` warn at default profile, block under `ZETETIC_PROFILE=strict`. Active only when `git commit` is invoked through Claude Code's hook system. |
| **Craftsmanship gate** | `tools/craftsmanship-checker.sh` mechanically enforces `coding-standards.md` §4 size limits + select structural rules. `FILE_TOO_LONG` (>500 lines) blocks; function/class/parameter/nesting block for recognized languages; grab-bag module names and layer-direction advise. Every threshold and per-rule severity (`block`/`advise`/`off`) is tunable per-repo via `.craftsmanship.conf`; defaults are the sourced §4 numbers. Runs at commit (local hook, changed files) and in CI (hard on newly-added files, informational full-tree sweep). Judgment rules (SRP/OCP/LSP/ISP, rule-of-three) are deliberately **not** mechanized, because a hook that fakes a verdict it can't reach just trains you to ignore it. |
| **650+ problem-shape triggers** | [`agents/genius/INDEX.md`](agents/genius/INDEX.md) maps natural-language problem descriptions to reasoning methods. <!-- source: 759 table content rows (grep -cE '^\|' agents/genius/INDEX.md = 843, minus 84 separator rows), counted 2026-06-23; "650+" is a conservative floor. --> |

---

## The reference library: 97 reasoning patterns

The problem-shaped skills above are the front door; this is the library behind it. Most AI agent libraries ship "pretend to be Einstein." This ships **Einstein's method** (gedankenexperiment, operational definitions, equivalence-principle reasoning) with the citations, the canonical moves, the documented blind spots, and the conditions under which the agent must refuse. Reasoning procedures, not personas.

A small sample, by problem shape:

| Domain | Agents | Example trigger |
|---|---|---|
| **Measurement & Signal** | Curie, Ekman, Wu | "the measurement exceeds what known parts predict" |
| **Causal & Abductive** | Pearl, Peirce, Snow/Hill | "does X cause Y, or is it confounded?" |
| **Formal & Correctness** | Dijkstra, Lamport, Pāṇini, Gödel, Turing | "can we prove this correct?" |
| **Failure & Resilience** | Hamilton, Taleb, Carnot, Boyd | "what happens when everything goes wrong?" |
| **Decision & Bias** | Kahneman, Schön, Roger Fisher, Simon | "is this decision driven by bias?" |
| **Ethics & Justice** | Rawls, Arendt, Le Guin, Ostrom | "who benefits and who bears the cost?" |

Full routing table (400+ triggers, pairings, composition chains) in [`agents/genius/INDEX.md`](agents/genius/INDEX.md).

---

## Compose chains: multi-agent pipelines

The most powerful skills *chain* reasoning procedures in sequence:

```
/performance-investigation     fermi → curie → knuth
  Bracket expected → measure actual → profile hot 3%

/incident-investigation        ginzburg → braudel → deming → peirce → hamilton
  Forensic trace → three timescales → common/special cause → root cause → remediation

/anomaly-to-explanation        mcclintock → curie → shannon
  Notice → isolate the carrier → formalize

/deep-research                 peirce → cochrane → feynman → toulmin
  Hypothesize → synthesize evidence → integrity check → structure argument

/autoresearch-loop             peirce → fisher → curie → laplace → schön
  Hypothesize → design experiment → measure → compare → detect diminishing returns
```

Each chain is a procedure. Each step is sourced. Each output declares what it was unable to verify.

---

## Autonomous build loop: draft, gate, and iterate on any repository

Beyond reasoning chains, the plugin ships a **closed-loop autonomous build** ([`.claude/workflows/autonomous-build-loop.js`](.claude/workflows/autonomous-build-loop.js)) that drives a build task to a candidate under a *deterministic acceptance gate*, on **any git repository, invoked from any working directory**, not just this one.

```
refine → plan → verify-plan → orchestrator build (isolated worktree)
       → deterministic gate + independent reviews → merge-on-green, else iterate
```

- **Repo-generic.** Pass `repoPath` (the target repo), `gateRunner`, and an optional base `gateConfig`; the loop branches, builds, and gates *that* repo and leaves its own working tree untouched. The gate tool (`tools/acceptance_gate.py`) gates any repo via `--root`, and evaluates the **committed** iteration tip via `--rev` (a throwaway detached worktree), so the verdict reflects what was committed, never a stray working tree.
- **The gate is external and deterministic.** A criterion passes iff its shell command exits 0, with no model grading its own output ([arXiv:2310.01798](https://arxiv.org/abs/2310.01798)). The loop *drafts and converges* a candidate; it does **not** self-certify. Two gate runners are cross-checked, reviewers are independent agent types, and an empty diff fails closed.
- **Fails closed; never touches `main`; never pushes.** Each iteration is isolated on its own branch + worktree; a rejected iteration is discarded with its gaps persisted to cross-session memory. The *authoritative* gate is a real exec **outside** the loop: a human or CI re-running the gate on the integration branch (against a pinned base SHA), before anything merges to `main`.

The acceptance gate is independently unit-tested (`tools/tests/acceptance-gate/`, including external-repo-from-a-foreign-cwd and fail-closed cases), and the loop has converged end-to-end on an external repository with the result independently re-gated.

**Honest limit:** git worktrees isolate *files*, not *runtime*. Spawned build sub-agents inherit the session's working directory, so the multi-agent build is most reliable when the loop is run **from the target repository's directory**. The deterministic gate, git operations, and branch isolation are fully cwd-independent; the file-writing build step is mitigated (dedicated worktree + absolute-path briefs) but not fully enforced by git alone.

---

## The Zetetic Standard

Every agent, skill, and hook inherits the same epistemic gates. Not optional.

| Pillar | Question |
|---|---|
| **Logical** | *Is it consistent?* |
| **Critical** | *Is it true?* |
| **Rational** | *Is it useful?* |
| **Essential** | *Is it necessary?* |

The rules:

1. No source → say *"I don't know"* and stop
2. Single source = hypothesis. Cross-reference required
3. Read the actual paper, not the blog post
4. No invented constants. Cite the equation or the data
5. Benchmark every change. No regressions accepted
6. *"I don't know"* preserves trust. Confident wrong answers destroy it
7. Actively seek disconfirming evidence

*Zetetic* (adj.): proceeding by inquiry; admitting nothing without proof.

---

## What this system does not do

The same standard applied to itself. Honest limits:

1. **Citation presence ≠ citation validity.** `// source: Knuth 1998` satisfies the checker whether or not Knuth 1998 exists or supports the constant. The hook enforces that a citation IS THERE, not that it's true.
2. **Hooks fire only inside Claude Code's invocation path.** Direct terminal commits, CI scripts, and other editors bypass the gates. A developer who works outside Claude Code is unaffected.
3. **Refusal conditions are intent, not contract.** Each genius agent documents conditions under which it should refuse; these are prompt-level guidance, not runtime guarantees. An agent can name a blind spot in its own description and exhibit it anyway.
4. **The checker has a narrow scope.** It flags absolute-claim keywords in comments, floats with 3+ decimals lacking `source:` annotations, and TODOs without issue references. It does **not** check code correctness, architectural soundness, or whether the reasoning in agent output is logically valid.
5. **Integer constants are not flagged by design.** `batch_size=128`, `timeout=30`, `max_retries=3` pass unchecked, because there would be too many false positives. Only floating-point constants with 3+ significant digits are gated.

These are documented because the gates are real, the limits are real, and overclaiming either undermines the standard the agents are supposed to enforce.

---

## Memory that survives sessions

Ships a local replica of Anthropic's [`memory_20250818`](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) tool with scope-based ACL: agents persist decisions, lessons, and project context to `/memories/<scope>/<file>` and recall them on every spawn. **6 memory suites** cover functional, ACL, concurrency, stale-lock, MCP and PII, and all of them run in CI on every push.

A `pre-tool-secret-shield` hook blocks any agent from reading `.env`, `.aws/credentials`, `*.pem`, `*.key`, or shell-history files, credentials the agent *can never need to read*. Full architecture: [`docs/MEMORY-MCP.md`](docs/MEMORY-MCP.md), contract: [`memory/contract.md`](memory/contract.md).

---

## Knowledge ingestion + a query-indexed semantic layer

Agents pull external knowledge into memory **without** an external SaaS dependency and **without** trusting an ungrounded claim. Three composable tools, each with a single responsibility:

- **Self-hosted web ingestion** ([`tools/web_ingest.py`](tools/web_ingest.py)): a dependency-free replica of Firecrawl's self-hostable core (`scrape` / `map` / `crawl`). Fetches with the standard library, respects `robots.txt`, extracts main-content markdown, and caches with conditional GET so revisiting a topic is cheap and incremental. It deliberately does **not** do web search or LLM extraction; it hands the agent clean markdown and the agent does the reasoning. Every fetched URL must be absolute HTTPS without embedded credentials, the rule is re-applied before following redirects, and TLS verification is never disabled.
- **Query-indexed semantic layer** ([`tools/semantic_layer.py`](tools/semantic_layer.py)): a YAML index ([`memory/semantic-layer.yaml`](memory/semantic-layer.yaml)) over Cortex memory, keyed by *query* and *intent* (`ingest` / `verify` / `compare` / `monitor`) with freshness states (`fresh` / `stale` / `superseded`). The layer never writes Cortex itself: the agent owns the Cortex write and passes back the `cortex_id` as a pointer, so the index and the store stay cleanly separated. Contract: [`memory/semantic-layer.schema.yaml`](memory/semantic-layer.schema.yaml).
- **Membership gate** ([`tools/manifest_gate.py`](tools/manifest_gate.py)): the fail-closed link between the two: every fact in a draft semantic-layer entry must be grounded in a URL the web-ingest engine **actually fetched this session**. The semantic layer can only check that a `source` string is *present*; this gate checks that it is *real*. A plausible-but-unfetched source is rejected (exit 3), not passed through. A pure `stdin → stdout` filter with no network or filesystem of its own.

How it's wired: the [`web-to-semantic`](skills/research/web-to-semantic.md) and [`semantic-ingest-loop`](skills/research/semantic-ingest-loop.md) skills drive the full `web_ingest → manifest_gate → semantic_layer` pipeline end-to-end (the three tools import none of each other, per DIP §5, and a skill is the single wiring point, so each stays independently testable and swappable), and the [`session-start-research`](hooks/session-start-research.sh) hook revalidates the layer every session. Honest limit: refresh is recall-driven, not a background daemon; a stale entry is surfaced and re-ingested the next time its topic comes up, it is not auto-refetched on a timer.

---

## A visible, enforced context budget

Every agent here follows a per-model **token-budget protocol** (`agents/orchestrator.md` → `<token-budget>`): checkpoint at ~180K tokens (Opus 4.8 / Sonnet 4.6) or ~120K (Haiku 4.5), with a 200K session soft cap. Left to prose, that protocol is easy to ignore. This plugin ships it as a **status line you can see** and a **hook that enforces it**, both from the companion [**session-optimizer**](https://github.com/cdeust/session-optimizer) repo (MIT).

- **`statusline-command.sh`**: a persistent two-line status bar. The context progress bar, percentage, and token count are colored **green → yellow → red** on the exact per-model threshold above, with a `⚠ save+recall` marker once you cross 200K. It also shows model, effort, git branch + dirty flag, worktree, PR badge, session cost, duration, and 5h/7d rate-limit usage, so the cost of *not* checkpointing is always on screen.
- **`hooks/stop-context-guard.py`** ([included here](hooks/stop-context-guard.py), registered as a `Stop` hook), reads the live token usage from the transcript and acts when you cross the line: at the checkpoint threshold it captures mechanical state (branch, last commit, modified files) **for free**, with no model tokens spent; at the 200K soft cap it blocks the stop **exactly once** and injects the checkpoint procedure, so the agent persists a scoped `memory-tool.sh` checkpoint and tells you to `/clear` and resume via `cortex:recall`. Loop-safe and non-fatal by construction.

Together they close the four failure modes of a long session: **context poisoning** (stale accumulation stops growing), **session poisoning** (a clean reset boundary is forced), **quota poisoning** (the 5h/7d budget isn't burned on oversized turns), and **runaway cost** (the largest-context turns are the most expensive). Install both from [session-optimizer](https://github.com/cdeust/session-optimizer); the `Stop` hook is wired into this plugin's [`hooks/hooks.json`](hooks/hooks.json) out of the box.

---

## Adopt in an existing project (gradual)

If your codebase has historical magic numbers and orphan TODOs, running `--staged` on every commit would be painful. The plugin supports a **transition profile**:

```bash
# .zetetic.conf at repo root
ZETETIC_PROFILE=permissive    # everything informational; never blocks
                              # → graduate to standard → strict over weeks
```

Size and structural limits adopt the same way, per-repo, in `.craftsmanship.conf` (the §4 thresholds are team-dependent by design, so they are configuration, not hard-coded into the gate):

```bash
# .craftsmanship.conf at repo root — defaults are the sourced §4 numbers
FILE_MAX=500                 # raise for a legacy tree, or grandfather per rule
SEV_FILE_TOO_LONG=block      # block | advise | off — every rule is tunable, incl. off
SEV_NESTING_TOO_DEEP=advise
```

A team that never writes the file gets the strict defaults; a team that disagrees edits one line instead of disabling the whole gate. Full migration path: [`docs/MIGRATION.md`](docs/MIGRATION.md).

---

## Companion projects

| Project | Role |
|---|---|
| [Cortex](https://github.com/cdeust/Cortex) | Local persistent memory + cognitive profiling that pre-loads your reasoning patterns at session start |
| [ai-architect-mcp-codebase](https://github.com/cdeust/ai-architect-mcp-codebase) | Codebase-intelligence MCP; agents query a property graph instead of `grep -r` |
| [prd-spec-generator](https://github.com/cdeust/prd-spec-generator) | TypeScript MCP that turns a feature description into a 9-file PRD with multi-judge verification using these agents |
| [session-optimizer](https://github.com/cdeust/session-optimizer) | Context-budget status line + `Stop` guard hook that makes the per-model checkpoint protocol visible and self-enforcing |

---

## Documentation

- [`docs/EXAMPLES.md`](docs/EXAMPLES.md): real session transcripts (bug caught, refusal fired, ADR generated)
- [`docs/COMPARE.md`](docs/COMPARE.md): vs vanilla Claude Code, Aider, Cline, Continue, Cursor agents
- [`docs/INSTALL.md`](docs/INSTALL.md): manual install, advanced config, model overrides
- [`docs/MIGRATION.md`](docs/MIGRATION.md): adopting in an existing non-compliant project
- [`docs/MEMORY-MCP.md`](docs/MEMORY-MCP.md): memory tool architecture + MCP server
- [`docs/AGENT-INTERNALS.md`](docs/AGENT-INTERNALS.md): agent file shape, frontmatter, routing
- [`docs/COUNTING.md`](docs/COUNTING.md): how every number this project states about itself is defined and measured
- [`docs/ROADMAP.md`](docs/ROADMAP.md): what the project intends to do, and not do, over the next 12 months
- [`GOVERNANCE.md`](GOVERNANCE.md): who decides, what a change needs to land, and what happens if the maintainer stops
- [`docs/ASSURANCE-CASE.md`](docs/ASSURANCE-CASE.md): threat model, trust boundaries, and the security argument with its limits
- [`agents/genius/INDEX.md`](agents/genius/INDEX.md): 400+ problem shapes → agent routing table
- [`rules/coding-standards.md`](rules/coding-standards.md): the engineering standard agents enforce

---

## License

MIT. See [LICENSE](LICENSE).

This software is the independent work of Clément Deust. It was developed
outside any employment relationship and is not affiliated with, endorsed by,
or owned by any past or present employer. It is part of the ai-architect
ecosystem ([Cortex](https://github.com/cdeust/Cortex),
[ai-architect-mcp-codebase](https://github.com/cdeust/ai-architect-mcp-codebase),
[prd-spec-generator](https://github.com/cdeust/prd-spec-generator)).

The reasoning patterns encoded in the 97 genius agents are derived from
published academic work cited in each agent's documentation (e.g., Pearl on
causal inference, Curie on measurement discipline, Dijkstra on program
correctness). The MIT license covers the encoding of those methods as agent
definitions and tooling; it does not assert ownership over the underlying
methods themselves, which remain attributable to their original authors and
publications.

---

<p align="center"><sub>Built by <a href="https://github.com/cdeust">cdeust</a>. All 120 agent files pass the <a href="tools/agent-definition-auditor.sh">structural auditor</a>. The system enforces source-citation discipline on the constants in its own commits.</sub></p>
