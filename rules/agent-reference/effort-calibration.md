---
name: effort-calibration
description: "Model selection (Opus/Sonnet/Haiku specs, cost, latency) and effort-level calibration rules"
read_when: "Choosing a model or effort level for a subagent; re-evaluating your own effort mid-task"
audience: team agents — loaded on demand via Read, never at spawn
---

## Model Selection & Effort Calibration

### Official model specs

Source: Anthropic model catalog (`claude-api` reference, cached 2026-06-24). Per-token throughput (TPS) is **not published for the 5-series** in that source — the column is therefore left empty rather than carried over from the 4.x figures (§8: no source, no number).

| Model | Model ID | Context | Max output | Cost (in/out MTok) | Latency | Best for |
|---|---|---|---|---|---|---|
| Claude Fable 5 | `claude-fable-5` | 1M | **128K** | $10 / $50 | — | Most demanding reasoning, longest-horizon autonomous work |
| Claude Opus 5 | `claude-opus-5` | 1M | **128K** | $5 / $25 | — | Hardest work, peak intelligence, sustained autonomy |
| Claude Opus 4.8 | `claude-opus-4-8` | 1M | **128K** | $5 / $25 | ~77 TPS | Previous Opus; still current for fallback routing |
| Claude Sonnet 5 | `claude-sonnet-5` | 1M | **128K** | $3 / $15 † | — | Near-Opus quality on coding & agentic work at Sonnet cost |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 1M | **128K** | $3 / $15 | ~72 TPS | Previous Sonnet |
| Claude Haiku 4.5 | `claude-haiku-4-5` | **200K** | **64K** | $1 / $5 | ~109 TPS | Executing pre-planned tasks, latency-sensitive, cost-sensitive |

† Sonnet 5 introductory pricing is $2 / $10 per MTok through **2026-08-31**, then $3 / $15.

**Haiku 4.5 hard constraints**: 200K context (= session limit, no slack) and 64K max output. At 136K context consumed only 64K output space remains — the hard ceiling. Haiku checkpoint triggers at ~120K, not 180K. Every other model above runs on 1M context with 128K max output, so their 200K/160K session budgets are conservative soft caps, not physical limits.

### Which model when (per Anthropic recommendation)

**Use Opus 5 when:**
- Long-horizon agent tasks requiring sustained autonomy with minimal oversight
- Deep, complex coding across large codebases — multi-file features, larger refactors, end-to-end work
- Code review and bug-finding (high precision *and* high recall, and it stays accurate at lower effort)
- Cybersecurity work requiring sustained focus across long traces
- Precision enterprise workflows (finance, legal, formal verification)
- Multimodal reasoning — pair it with crop/analyze/verify tools rather than raising thinking

**Use Sonnet 5 when:**
- Agent planning & execution (building workflows, not just following them)
- Agile coding — iterating on a feature, not just executing a spec
- Agent prototyping and development cycles
- Production-ready applications
- Efficient research

**Use Fable 5 only when explicitly chosen** — it is not the default upgrade path from Opus and costs 2× Opus rates.

**Use Haiku 4.5 when:**
- The task has been fully planned by a more capable model and execution is mechanical
- Latency-sensitive path (user-facing, real-time)
- Content generation at scale (ad copy, templating, formatting)
- Efficient research on bounded, well-specified questions

### Effort levels — controls thinking depth and overall token spend

**No longer Opus-only.** The full `low` / `medium` / `high` / `xhigh` / `max` ladder is supported on **Opus 5, Sonnet 5, Fable 5, Opus 4.8 and Opus 4.7**; Sonnet 5 is the first Sonnet-tier model with `xhigh`. The API default is `high`.

Two Opus 5 specifics that change how this table is applied:
- **Thinking is on by default.** Omitting the thinking parameter runs adaptive thinking (on Opus 4.8 it meant *no* thinking). Session budget caps thinking + response together, so a route that used to run thinking-off now consumes more of it.
- **Disabling thinking is capped at `high` effort.** Pairing disabled thinking with `xhigh` or `max` is rejected outright. Prefer `low`/`medium` with thinking on over disabling it — Opus 5 is unusually strong at the low end, and that is the cheaper lever.

| Task | Effort | Rationale |
|---|---|---|
| Reading files, I/O, listing | low | No reasoning required |
| Implementing a fully-specified plan | low | Plan already did the reasoning |
| Bug fix with clear root cause | low–medium | Light application of judgment |
| Architecture decision, PRD | medium | Structured reasoning over bounded search space |
| Multi-disciplinary analysis, research synthesis | medium | Judgment required but not open-ended |
| Formal verification, concurrency proof, security audit | high | Correctness is load-bearing; wrong answer is worse than slow |
| Genuinely stuck / surprising result / blocker | high | Use extended thinking to break impasse |

**Rules:**
- **Never default to high effort** — it is a deliberate escalation, not a fallback. On Opus 5 specifically, sweep downward before settling: `low` and `medium` punch well above their weight, and effort defaults carried over from a prior model rarely transfer.
- **Prefer fast mode** (`/fast`) for Opus 5 or Opus 4.8 tasks where peak correctness is not required — 2.5× output speed at the same intelligence ($10/$50 MTok fast mode vs $5/$25 standard). Fast mode exists on Opus 5 and Opus 4.8 only, and only on the first-party API.
- **Re-evaluate per subtask**: drop effort when a subtask proves simpler than expected; escalate only for that subtask when it proves harder.
- **Token budget interaction**: high effort burns more tokens per turn. Near the 200K session limit, prefer medium/low + checkpoint over burning budget on extended thinking.
- **Cost-aware orchestration**: an opus high-effort turn costs ~50× a haiku turn. Use haiku for parallelizable mechanical subtasks after opus has produced the plan.
