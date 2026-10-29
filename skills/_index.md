# Skills Index

This index covers 86 skills: 15 problem-shaped entry points (`<name>/SKILL.md`) plus 71 category skills. Every skill carries the zetetic standard: four pillar gates, sourced evidence, and explicit refusal conditions.

## Problem-shaped entry points (start here)

Each wraps a cluster of genius-agent categories from [`agents/genius/INDEX.md`](../agents/genius/INDEX.md) and loads the best-fit agent on demand via `tools/genius-invoker.sh`:

| Skill | Problem shape |
|-------|---------------|
| [`measurement-discipline`](measurement-discipline/SKILL.md) | untrusted metrics, unbalanced ledgers, missing instruments |
| [`estimation`](estimation/SKILL.md) | decisions blocked by missing data; false precision; capacity/feasibility bounds |
| [`causal-audit`](causal-audit/SKILL.md) | causation claimed from correlation; experiment design; confounding |
| [`formal-correctness`](formal-correctness/SKILL.md) | spec-less concurrent/distributed code; contracts; decidability |
| [`failure-forensics`](failure-forensics/SKILL.md) | incidents, discarded anomalies, undesigned degraded modes |
| [`decision-bias-check`](decision-bias-check/SKILL.md) | intuition-driven high-stakes calls; unfalsifiable claims; gamed metrics |
| [`evidence-synthesis`](evidence-synthesis/SKILL.md) | conflicting sources into one graded, warranted claim |
| [`systems-leverage`](systems-leverage/SKILL.md) | structural dysfunction that resists local fixes; where to intervene |
| [`boundary-design`](boundary-design/SKILL.md) | build-vs-buy, module/team/API boundaries, abstraction placement |
| [`structure-discovery`](structure-discovery/SKILL.md) | hidden regularities, reverse engineering, taxonomy gaps |
| [`problem-reframing`](problem-reframing/SKILL.md) | malformed questions, false binaries, denied trade-offs |
| [`normative-design`](normative-design/SKILL.md) | fairness and legitimacy of rules; open-texture cases; diffuse responsibility |
| [`narrative-sensemaking`](narrative-sensemaking/SKILL.md) | accounts to reconstruct; sequence gaps; structurally implausible claims |
| [`representation-and-possibility`](representation-and-possibility/SKILL.md) | notation obscuring the solution; unbounded option spaces; result before proof |
| [`experience-and-transmission`](experience-and-transmission/SKILL.md) | correct artifacts nobody can use, learn, or read; observer inside the system |

## Quick Reference

The Agents column names the genius patterns the skill applies. Only genius agents exist (owner decision 2026-10-21): delegate a skill's work to a built-in `general-purpose`, `Explore` or `Plan` agent and put `GENIUS: <name>[, <name>]` (1 or 2 of the names below) on its own line in the prompt. `hooks/pre-agent-genius-gate.py` denies the call otherwise.

| Skill | Category | Agents | One-line |
|-------|----------|--------|----------|
| `/verify-claim` | zetetic | cochrane, feynman | Verify a claim against multiple independent primary sources |
| `/difficulty-book` | zetetic | darwin, feynman | Catalog observations that contradict the current theory |
| `/cargo-cult-check` | zetetic | feynman | Detect procedures followed without causal mechanism |
| `/seek-disconfirmation` | zetetic | darwin, feynman, mcclintock | Actively hunt evidence against a hypothesis |
| `/review` | engineering | popper, simon | Code review: Clean Architecture, SOLID, layer integrity |
| `/implement` | engineering | dijkstra, simon, popper | Feature implementation with layer-aware design |
| `/refactor` | engineering | simon, dijkstra, popper | Structural refactoring with incremental steps |
| `/debug` | engineering | dijkstra, curie | Root-cause debugging with instrumentation and bisection |
| `/optimize` | engineering | knuth, dijkstra, curie | Profile first, fix the 3%, leave the 97% alone |
| `/secure` | engineering | taleb, dijkstra | Threat model + OWASP + supply chain + defense-in-depth |
| `/test` | engineering | popper, dijkstra | Test suite design acknowledging what tests can't prove |
| `/deploy` | engineering | hamilton, dijkstra | Deployment with rollback, monitoring, and blast-radius assessment |
| `/migrate-db` | engineering | lavoisier, dijkstra | Database migration with mass-balance data verification |
| `/estimate` | analysis | fermi | Fermi decomposition: bracket, cross-check, dominant uncertainty |
| `/investigate` | analysis | peirce | Structured investigation routing to genius agents by problem shape |
| `/benchmark` | analysis | curie, dijkstra, fisher | Before/after measurement with statistical comparison |
| `/balance` | analysis | lavoisier, curie | Conservation audit: enumerate flows, close the ledger |
| `/experiment` | analysis | fisher | Controlled experiment: randomize, block, replicate, pre-specify |
| `/audit-integrity` | analysis | feynman, darwin | Integrity check: self-deception, cargo cults, missing limitations |
| `/decompose` | architecture | simon, dijkstra, kekule | Module decomposition: forces, boundaries, dependency graph |
| `/adr` | architecture | simon, darwin | Architecture Decision Record with difficulty-book per option |
| `/spec` | architecture | lamport, simon | Formal specification: states, transitions, invariants, failure model |
| `/contract` | architecture | liskov, simon | Behavioral contracts: pre/post/invariant/history constraint |
| `/evaluate-tool` | architecture | hopper, engelbart, simon, feynman | Tool evaluation with cargo-cult and obsolescence checks |
| `/design` | design | jobs | UX/UI design and WCAG 2.2 AA accessibility audit |
| `/goal` | loop | dijkstra | Compile a request into a goal contract with executable acceptance checks (portable) |
| `/plan` | loop | simon, dijkstra | Plan an active goal and verify the plan against its criteria (portable) |
| `/verify-goal` | loop | popper | Run every acceptance check of a goal and ledger the evidence (portable) |
| `/refine-goal` | loop | popper | Turn a verification ledger into the next iteration's backlog (portable) |
| `/advisor-model` | loop | (native advisor tool) | Consult a separate model at a selected plan, fork, or completion decision (portable) |
| `/literature-review` | research | cochrane | Systematic search: find papers, read them, assess applicability |
| `/explain` | research | vygotsky, feynman | Multi-level explanation with understanding-gap diagnostic |
| `/write-paper` | research | toulmin | Paper draft with claim-evidence chains and difficulty-book limitations |
| `/pre-submit-review` | research | popper, feynman | Simulated peer review with integrity check |
| `/design-experiment` | research | fisher | Experimental design for research: ablations, controls, seeds |
| `/performance-investigation` | compose | fermi → curie → knuth | Bracket → measure → profile → fix the 3% |
| `/anomaly-to-explanation` | compose | mcclintock → curie → shannon/noether | Notice → isolate → formalize |
| `/conjecture-to-code` | compose | ramanujan → dijkstra/lamport → dijkstra | Generate → prove → implement (prover mandatory) |
| `/failure-resilient-design` | compose | hamilton → lamport → dijkstra | Degrade → specify → build |
| `/product-quality-audit` | compose | jobs → galileo → dijkstra | Experience spec → strip to essential → verify |
| `/new-tool-design` | compose | engelbart → hopper → kay → jobs | Augment → abstract → make malleable → integrate |
| `/statistical-intervention` | compose | semmelweis → fisher → feynman | Detect anomaly → design experiment → integrity-check → communicate |

## By Category

### Zetetic (methodology backbone)
4 skills — the epistemic foundation that every other skill inherits.

### Engineering (daily workflows)
9 skills — review, implement, refactor, debug, optimize, secure, test, deploy, migrate.

### Analysis (investigation and measurement)
6 skills — estimate, investigate, benchmark, balance, experiment, audit-integrity.

### Architecture (structural decisions)
5 skills — decompose, adr, spec, contract, evaluate-tool.

### Loop (goal-driven iteration)

5 skills, packaged as `plugins/zetetic-loop` for Codex and Gemini CLI: goal, plan, verify-goal, refine-goal, advisor-model. Driven on Claude Code by `/zetetic:goal-loop` under the native `/goal` or `/loop`.

### Design (UX/UI)
1 skill — design (UX audit, WCAG 2.2 AA compliance, heuristic evaluation).

### Research (academic and ML)
5 skills — literature-review, explain, write-paper, pre-submit-review, design-experiment.

### Compose (multi-agent chains)
7 skills — performance-investigation, anomaly-to-explanation, conjecture-to-code, failure-resilient-design, product-quality-audit, new-tool-design, statistical-intervention.
