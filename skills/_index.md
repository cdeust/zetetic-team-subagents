# Skills Index

This index covers 80 skills: 15 problem-shaped entry points (`<name>/SKILL.md`) plus 65 category skills. Every skill carries the zetetic standard: four pillar gates, sourced evidence, and explicit refusal conditions.

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

| Skill | Category | Agents | One-line |
|-------|----------|--------|----------|
| `/verify-claim` | zetetic | research-scientist, feynman | Verify a claim against multiple independent primary sources |
| `/difficulty-book` | zetetic | darwin, feynman | Catalog observations that contradict the current theory |
| `/cargo-cult-check` | zetetic | feynman | Detect procedures followed without causal mechanism |
| `/seek-disconfirmation` | zetetic | darwin, feynman, mcclintock | Actively hunt evidence against a hypothesis |
| `/review` | engineering | code-reviewer, architect | Code review: Clean Architecture, SOLID, layer integrity |
| `/implement` | engineering | engineer, architect, test-engineer | Feature implementation with layer-aware design |
| `/refactor` | engineering | architect, engineer, test-engineer | Structural refactoring with incremental steps |
| `/debug` | engineering | engineer, curie | Root-cause debugging with instrumentation and bisection |
| `/optimize` | engineering | knuth, engineer, curie | Profile first, fix the 3%, leave the 97% alone |
| `/secure` | engineering | security-auditor, engineer | Threat model + OWASP + supply chain + defense-in-depth |
| `/test` | engineering | test-engineer, dijkstra | Test suite design acknowledging what tests can't prove |
| `/deploy` | engineering | devops-engineer, engineer, hamilton | Deployment with rollback, monitoring, and blast-radius assessment |
| `/migrate-db` | engineering | dba, engineer, lavoisier | Database migration with mass-balance data verification |
| `/estimate` | analysis | fermi | Fermi decomposition: bracket, cross-check, dominant uncertainty |
| `/investigate` | analysis | orchestrator (routes by shape) | Structured investigation routing to genius agents by problem shape |
| `/benchmark` | analysis | curie, engineer, fisher | Before/after measurement with statistical comparison |
| `/balance` | analysis | lavoisier, curie | Conservation audit: enumerate flows, close the ledger |
| `/experiment` | analysis | fisher, experiment-runner | Controlled experiment: randomize, block, replicate, pre-specify |
| `/audit-integrity` | analysis | feynman, darwin | Integrity check: self-deception, cargo cults, missing limitations |
| `/decompose` | architecture | architect, engineer, kekule | Module decomposition: forces, boundaries, dependency graph |
| `/adr` | architecture | architect, darwin | Architecture Decision Record with difficulty-book per option |
| `/spec` | architecture | lamport, architect | Formal specification: states, transitions, invariants, failure model |
| `/contract` | architecture | liskov, architect | Behavioral contracts: pre/post/invariant/history constraint |
| `/evaluate-tool` | architecture | hopper, engelbart, architect, feynman | Tool evaluation with cargo-cult and obsolescence checks |
| `/literature-review` | research | research-scientist | Systematic search: find papers, read them, assess applicability |
| `/explain` | research | professor, feynman | Multi-level explanation with understanding-gap diagnostic |
| `/write-paper` | research | paper-writer, latex-engineer | Paper draft with claim-evidence chains and difficulty-book limitations |
| `/pre-submit-review` | research | reviewer-academic, feynman | Simulated peer review with integrity check |
| `/design-experiment` | research | fisher, experiment-runner | Experimental design for research: ablations, controls, seeds |
| `/performance-investigation` | compose | fermi → curie → knuth | Bracket → measure → profile → fix the 3% |
| `/anomaly-to-explanation` | compose | mcclintock → curie → shannon/noether | Notice → isolate → formalize |
| `/conjecture-to-code` | compose | ramanujan → dijkstra/lamport → engineer | Generate → prove → implement (prover mandatory) |
| `/failure-resilient-design` | compose | hamilton → lamport → engineer | Degrade → specify → build |
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

### Research (academic and ML)
5 skills — literature-review, explain, write-paper, pre-submit-review, design-experiment.

### Compose (multi-agent chains)
7 skills — performance-investigation, anomaly-to-explanation, conjecture-to-code, failure-resilient-design, product-quality-audit, new-tool-design, statistical-intervention.
