<p align="center">
  <img src="assets/banner.svg" alt="Zetetic Agents — 97 reasoning patterns, one epistemic standard" width="100%"/>
</p>

<p align="center">
  <a href="https://github.com/cdeust/zetetic-team-subagents/actions/workflows/ci.yml"><img src="https://github.com/cdeust/zetetic-team-subagents/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-288-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/agents-118-8A2BE2" alt="Agents">
  <img src="https://img.shields.io/badge/skills-64-green" alt="Skills">
  <img src="https://img.shields.io/badge/hooks-18_lifecycle-red" alt="Hooks">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT License"></a>
</p>

> **Claude Code agents whose commits are blocked when constants lack source citations.**
> 97 genius reasoning agents (plus 21 team-role agents = 118 total) each citing their primary paper and documenting their refusal conditions, paired with a pre-commit hook that blocks any floating-point constant with 3+ significant digits that lacks a `source:` annotation.
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

97 reasoning patterns drawn from primary sources — Dijkstra's correctness discipline, Curie's residual-with-a-carrier method, Hamilton's fault-tolerance protocol, Cochrane's evidence synthesis — routed automatically to your problem by *shape*, not by *field*. Every output is sourced. Every commit is checked. The standard is not a prompt. It is a gate.

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

```bash
claude plugin marketplace add cdeust/zetetic-team-subagents
claude plugin install zetetic-team-subagents
```

That's the whole install. The plugin's installer copies agents, skills, hooks, and tools into `~/.claude/`. Manual install + advanced config: [`docs/INSTALL.md`](docs/INSTALL.md).

---

## What you actually get

| Capability | What it gives you (concretely) |
|---|---|
| **97 documented refusals** | Each genius agent's body documents conditions under which it refuses (when to stop, what to cite, when to hand off). Refusal conditions are intent statements, not enforced contracts. |
| **64 multi-step workflows** | Type one slash command, get a sourced research brief / debugging trace / ADR. Each agent in the chain produces output and declares what it could not verify. |
| **Commit-time gates** | `pre-commit-zetetic.sh` blocks commits with `UNSOURCED` keywords (always/never/obviously) at any profile. `MAGIC_NUMBER` floats (3+ decimals without `source:`) and `TODO_NO_REF` warn at default profile, block under `ZETETIC_PROFILE=strict`. Active only when `git commit` is invoked through Claude Code's hook system. |
| **Craftsmanship gate** | `tools/craftsmanship-checker.sh` mechanically enforces `coding-standards.md` §4 size limits + select structural rules. `FILE_TOO_LONG` (>500 lines) blocks; function/class/parameter/nesting block for recognized languages; grab-bag module names and layer-direction advise. Every threshold and per-rule severity (`block`/`advise`/`off`) is tunable per-repo via `.craftsmanship.conf` — defaults are the sourced §4 numbers. Runs at commit (local hook, changed files) and in CI (hard on newly-added files, informational full-tree sweep). Judgment rules (SRP/OCP/LSP/ISP, rule-of-three) are deliberately **not** mechanized — a hook that fakes a verdict it can't reach just trains you to ignore it. |
| **650+ problem-shape triggers** | [`agents/genius/INDEX.md`](agents/genius/INDEX.md) maps natural-language problem descriptions to reasoning methods. <!-- source: 759 table content rows (grep -cE '^\|' agents/genius/INDEX.md = 843, minus 84 separator rows), counted 2026-06-23; "650+" is a conservative floor. --> |

---

## Reasoning procedures, not personas

Most AI agent libraries ship "pretend to be Einstein." This ships **Einstein's method** — gedankenexperiment, operational definitions, equivalence-principle reasoning — with the citations, the canonical moves, the documented blind spots, and the conditions under which the agent must refuse.

A small sample, by problem shape:

| Domain | Agents | Example trigger |
|---|---|---|
| **Measurement & Signal** | Curie, Ekman, Wu | "the measurement exceeds what known parts predict" |
| **Causal & Abductive** | Pearl, Peirce, Snow/Hill | "does X cause Y, or is it confounded?" |
| **Formal & Correctness** | Dijkstra, Lamport, Pāṇini, Gödel, Turing | "can we prove this correct?" |
| **Failure & Resilience** | Hamilton, Taleb, Carnot, Boyd | "what happens when everything goes wrong?" |
| **Decision & Bias** | Kahneman, Schön, Roger Fisher, Simon | "is this decision driven by bias?" |
| **Ethics & Justice** | Rawls, Arendt, Le Guin, Ostrom | "who benefits and who bears the cost?" |

Full routing table — 400+ triggers, pairings, composition chains — in [`agents/genius/INDEX.md`](agents/genius/INDEX.md).

---

## Compose chains — multi-agent pipelines

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

## Autonomous build loop — draft, gate, and iterate on any repository

Beyond reasoning chains, the plugin ships a **closed-loop autonomous build** ([`.claude/workflows/autonomous-build-loop.js`](.claude/workflows/autonomous-build-loop.js)) that drives a build task to a candidate under a *deterministic acceptance gate* — on **any git repository, invoked from any working directory**, not just this one.

```
refine → plan → verify-plan → orchestrator build (isolated worktree)
       → deterministic gate + independent reviews → merge-on-green, else iterate
```

- **Repo-generic.** Pass `repoPath` (the target repo), `gateRunner`, and an optional base `gateConfig`; the loop branches, builds, and gates *that* repo and leaves its own working tree untouched. The gate tool (`tools/acceptance_gate.py`) gates any repo via `--root`, and evaluates the **committed** iteration tip via `--rev` (a throwaway detached worktree) — so the verdict reflects what was committed, never a stray working tree.
- **The gate is external and deterministic.** A criterion passes iff its shell command exits 0 — no model grading its own output ([arXiv:2310.01798](https://arxiv.org/abs/2310.01798)). The loop *drafts and converges* a candidate; it does **not** self-certify. Two gate runners are cross-checked, reviewers are independent agent types, and an empty diff fails closed.
- **Fails closed; never touches `main`; never pushes.** Each iteration is isolated on its own branch + worktree; a rejected iteration is discarded with its gaps persisted to cross-session memory. The *authoritative* gate is a real exec **outside** the loop — a human or CI re-running the gate on the integration branch (against a pinned base SHA) — before anything merges to `main`.

The acceptance gate is independently unit-tested (`tools/tests/acceptance-gate/`, including external-repo-from-a-foreign-cwd and fail-closed cases), and the loop has converged end-to-end on an external repository with the result independently re-gated.

**Honest limit:** git worktrees isolate *files*, not *runtime* — spawned build sub-agents inherit the session's working directory, so the multi-agent build is most reliable when the loop is run **from the target repository's directory**. The deterministic gate, git operations, and branch isolation are fully cwd-independent; the file-writing build step is mitigated (dedicated worktree + absolute-path briefs) but not fully enforced by git alone.

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
3. **Refusal conditions are intent, not contract.** Each genius agent documents conditions under which it should refuse — these are prompt-level guidance, not runtime guarantees. An agent can name a blind spot in its own description and exhibit it anyway.
4. **The checker has a narrow scope.** It flags absolute-claim keywords in comments, floats with 3+ decimals lacking `source:` annotations, and TODOs without issue references. It does **not** check code correctness, architectural soundness, or whether the reasoning in agent output is logically valid.
5. **Integer constants are not flagged by design.** `batch_size=128`, `timeout=30`, `max_retries=3` pass unchecked — too many false positives. Only floating-point constants with 3+ significant digits are gated.

These are documented because the gates are real, the limits are real, and overclaiming either undermines the standard the agents are supposed to enforce.

---

## Memory that survives sessions

Ships a local replica of Anthropic's [`memory_20250818`](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) tool with scope-based ACL: agents persist decisions, lessons, and project context to `/memories/<scope>/<file>` and recall them on every spawn. **241 tests passing** across functional, ACL, concurrency, stale-lock, MCP, and PII suites.

A `pre-tool-secret-shield` hook blocks any agent from reading `.env`, `.aws/credentials`, `*.pem`, `*.key`, or shell-history files — credentials the agent *can never need to read*. Full architecture: [`docs/MEMORY-MCP.md`](docs/MEMORY-MCP.md), contract: [`memory/contract.md`](memory/contract.md).

---

## Knowledge ingestion + a query-indexed semantic layer

Agents pull external knowledge into memory **without** an external SaaS dependency and **without** trusting an ungrounded claim. Three composable tools, each with a single responsibility:

- **Self-hosted web ingestion** ([`tools/web_ingest.py`](tools/web_ingest.py)) — a dependency-free replica of Firecrawl's self-hostable core (`scrape` / `map` / `crawl`). Fetches with the standard library, respects `robots.txt`, extracts main-content markdown, and caches with conditional GET so revisiting a topic is cheap and incremental. It deliberately does **not** do web search or LLM extraction — it hands the agent clean markdown and the agent does the reasoning. TLS verification is never disabled.
- **Query-indexed semantic layer** ([`tools/semantic_layer.py`](tools/semantic_layer.py)) — a YAML index ([`memory/semantic-layer.yaml`](memory/semantic-layer.yaml)) over Cortex memory, keyed by *query* and *intent* (`ingest` / `verify` / `compare` / `monitor`) with freshness states (`fresh` / `stale` / `superseded`). The layer never writes Cortex itself: the agent owns the Cortex write and passes back the `cortex_id` as a pointer, so the index and the store stay cleanly separated. Contract: [`memory/semantic-layer.schema.yaml`](memory/semantic-layer.schema.yaml).
- **Membership gate** ([`tools/manifest_gate.py`](tools/manifest_gate.py)) — the fail-closed link between the two: every fact in a draft semantic-layer entry must be grounded in a URL the web-ingest engine **actually fetched this session**. The semantic layer can only check that a `source` string is *present*; this gate checks that it is *real*. A plausible-but-unfetched source is rejected (exit 3), not passed through. A pure `stdin → stdout` filter with no network or filesystem of its own.

How it's wired: the [`web-to-semantic`](skills/research/web-to-semantic.md) and [`semantic-ingest-loop`](skills/research/semantic-ingest-loop.md) skills drive the full `web_ingest → manifest_gate → semantic_layer` pipeline end-to-end (the three tools import none of each other — DIP, §5 — and a skill is the single wiring point, so each stays independently testable and swappable), and the [`session-start-research`](hooks/session-start-research.sh) hook revalidates the layer every session. Honest limit: refresh is recall-driven, not a background daemon — a stale entry is surfaced and re-ingested the next time its topic comes up, it is not auto-refetched on a timer.

---

## A visible, enforced context budget

Every agent here follows a per-model **token-budget protocol** (`agents/orchestrator.md` → `<token-budget>`): checkpoint at ~180K tokens (Opus 4.8 / Sonnet 4.6) or ~120K (Haiku 4.5), with a 200K session soft cap. Left to prose, that protocol is easy to ignore. This plugin ships it as a **status line you can see** and a **hook that enforces it** — both from the companion [**session-optimizer**](https://github.com/cdeust/session-optimizer) repo (MIT).

- **`statusline-command.sh`** — a persistent two-line status bar. The context progress bar, percentage, and token count are colored **green → yellow → red** on the exact per-model threshold above, with a `⚠ save+recall` marker once you cross 200K. It also shows model, effort, git branch + dirty flag, worktree, PR badge, session cost, duration, and 5h/7d rate-limit usage — so the cost of *not* checkpointing is always on screen.
- **`hooks/stop-context-guard.py`** ([included here](hooks/stop-context-guard.py), registered as a `Stop` hook) — reads the live token usage from the transcript and acts when you cross the line: at the checkpoint threshold it captures mechanical state (branch, last commit, modified files) **for free**, with no model tokens spent; at the 200K soft cap it blocks the stop **exactly once** and injects the checkpoint procedure, so the agent persists a scoped `memory-tool.sh` checkpoint and tells you to `/clear` and resume via `cortex:recall`. Loop-safe and non-fatal by construction.

Together they close the four failure modes of a long session — **context poisoning** (stale accumulation stops growing), **session poisoning** (a clean reset boundary is forced), **quota poisoning** (the 5h/7d budget isn't burned on oversized turns), and **runaway cost** (the largest-context turns are the most expensive). Install both from [session-optimizer](https://github.com/cdeust/session-optimizer); the `Stop` hook is wired into this plugin's [`hooks/hooks.json`](hooks/hooks.json) out of the box.

---

## Adopt in an existing project (gradual)

If your codebase has historical magic numbers and orphan TODOs, running `--staged` on every commit would be painful. The plugin supports a **transition profile**:

```bash
# .zetetic.conf at repo root
ZETETIC_PROFILE=permissive    # everything informational; never blocks
                              # → graduate to standard → strict over weeks
```

Size and structural limits adopt the same way — per-repo, in `.craftsmanship.conf` (the §4 thresholds are team-dependent by design, so they are configuration, not hard-coded into the gate):

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
| [Cortex](https://github.com/cdeust/Cortex) | Local persistent memory + cognitive profiling — pre-loads your reasoning patterns at session start |
| [automatised-pipeline](https://github.com/cdeust/automatised-pipeline) | Codebase-intelligence MCP — agents query a property graph instead of `grep -r` |
| [prd-spec-generator](https://github.com/cdeust/prd-spec-generator) | TypeScript MCP that turns a feature description into a 9-file PRD with multi-judge verification using these agents |
| [session-optimizer](https://github.com/cdeust/session-optimizer) | Context-budget status line + `Stop` guard hook — makes the per-model checkpoint protocol visible and self-enforcing |

---

## Documentation

- [`docs/EXAMPLES.md`](docs/EXAMPLES.md) — real session transcripts (bug caught, refusal fired, ADR generated)
- [`docs/COMPARE.md`](docs/COMPARE.md) — vs vanilla Claude Code, Aider, Cline, Continue, Cursor agents
- [`docs/INSTALL.md`](docs/INSTALL.md) — manual install, advanced config, model overrides
- [`docs/MIGRATION.md`](docs/MIGRATION.md) — adopting in an existing non-compliant project
- [`docs/MEMORY-MCP.md`](docs/MEMORY-MCP.md) — memory tool architecture + MCP server
- [`docs/AGENT-INTERNALS.md`](docs/AGENT-INTERNALS.md) — agent file shape, frontmatter, routing
- [`agents/genius/INDEX.md`](agents/genius/INDEX.md) — 400+ problem shapes → agent routing table
- [`rules/coding-standards.md`](rules/coding-standards.md) — the engineering standard agents enforce

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center"><sub>Built by <a href="https://github.com/cdeust">cdeust</a>. All 117 agent files pass the <a href="tools/agent-definition-auditor.sh">structural auditor</a>. The system enforces source-citation discipline on the constants in its own commits.</sub></p>
