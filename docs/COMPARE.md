# Compare — How zetetic relates to other agent tools

This document is structured as **question → tool**, not **tool → score**. Each tool answers a different question well, and the questions are not substitutable. Pick the tool whose question matches yours.

> **The honest spine:** each tool is a good answer to a different question. There is no single comparable scale for "agent quality." Comparing on one is a category error.

---

## The question your tool should answer

Find your row. The right tool is in the row, not the column.

| Your question | Tool that fits | Why |
|---|---|---|
| *"I want a collaborator that proposes targeted edits to my files while I supervise."* | **[Aider](https://aider.chat/)** | Pair-programming via diff loops. Proposal → review → apply. |
| *"I want suggestions appearing inline as I type, aware of my open files."* | **[Cursor](https://cursor.sh/)** agents | Editor-ambient, latency-sensitive completion. |
| *"I want to ask questions about my codebase and get answers with file citations."* | **[Continue.dev](https://continue.dev/)** | Chat-driven retrieval over a local corpus. |
| *"I want to give a goal and have the tool figure out and execute the steps."* | **[Cline](https://github.com/cline/cline)**, vanilla **[Claude Code](https://claude.ai/code)** | Autonomous goal decomposition + subprocess orchestration. |
| *"I want claims traced to sources, refusal conditions documented, magic numbers blocked at commit-time."* | **zetetic-team-subagents** (this repo) | Epistemic enforcement + reasoning-procedure injection. |

If your question matches more than one row, you probably want more than one tool. Most of these compose; they're not in zero-sum competition.

---

## Word disambiguation — these terms mean different things across tools

When you read "X has memory" or "Y has agents," check the meaning. Same words, different games.

### "agent"

| Tool | What "agent" means there |
|---|---|
| Claude Code | A subprocess role with its own system prompt, tool pool, and model — invoked via `Task` |
| Continue.dev | A chat persona with assigned tool access and a context recipe |
| Cline | An autonomous goal-executor that plans steps and runs them |
| zetetic | A documented reasoning procedure (canonical moves, blind spots, refusal conditions, hand-off protocol) — text + a routing slug |

### "context"

| Tool | What "context" means |
|---|---|
| Most chat tools | The active scrollback window |
| Cursor | Your open files, semantic embedding of nearby code |
| Continue | Retrieval over a configured corpus |
| Cline | Project-tree summary plus active task state |
| zetetic | Primary-source citations chained from your prompt to a published reference |

### "tool"

| Tool | What "tool" means |
|---|---|
| OpenAI / Anthropic API | A model-callable function in the tool list |
| Cursor / Continue | An IDE plugin |
| Aider / Claude Code | A CLI or REPL command |
| zetetic | A published methodology with documented refusal conditions |

### "memory"

| Tool | What "memory" means |
|---|---|
| Most chat tools | The scrollback window of the current session |
| Claude Code | File-system recall via `Read`/`Glob`/`Grep` |
| Cline (with plugins) | A persistent vector store keyed on past tasks |
| zetetic + Cortex | Scoped semantic memory with EMA updates and per-agent ACL — see [`memory/contract.md`](../memory/contract.md) |

When this doc says "X has memory," check which sense of memory.

---

## Comparisons this doc refuses to make

### 1. "Zetetic does better code reviews than Aider."

Aider's game is diff application; the review there is whether the diff applies cleanly and produces working code. Zetetic's game is reasoning-procedure enforcement; the review there is whether the constants are sourced and whether the agent refused appropriately. **These are not the same review.** Comparing them on a single "code review quality" axis is a category error.

### 2. "Continue.dev has worse memory than zetetic."

Continue's memory is retrieval over a file corpus — a library card catalog. Zetetic + Cortex memory is epistemological session state — what was decided, what was tried, what was refused. **Comparing them is comparing a card catalog to a personal cognitive profile.** They serve different purposes, neither subsumes the other.

### 3. "Cursor is less accurate than zetetic."

Accuracy in Cursor's game = token-prediction fitness to the user's intent mid-keystroke. Accuracy in zetetic's game = claim-to-source traceability. **These are incommensurable.** A tool that's "100% accurate" in one sense can be irrelevant in the other.

---

## Compound claims this doc refuses to make

| Claim | Why it's incoherent |
|---|---|
| "Zetetic catches N% more issues" | "Issues" is defined differently in each tool's game. Aider's issue = failed diff; Cursor's issue = stale completion; zetetic's issue = unsourced constant. The percentage crosses category boundaries and means nothing. |
| "Zetetic produces higher-quality output" | "Quality" is a thick concept: patch correctness (Aider), retrieval precision (Continue), completion fitness (Cursor), evidence traceability (zetetic). One number cannot span all four. |
| "Zetetic is more agentic than Cline" | "Agentic" conflates autonomy-of-execution (Cline's game) with rigor-of-reasoning-procedure (zetetic's game). These are orthogonal. |

---

## Composing tools — where they actually meet

These tools are not mutually exclusive. The realistic stack often combines:

| Combination | Use case |
|---|---|
| Cursor + zetetic hooks | Inline completion in the editor; commits gated by zetetic-checker |
| Aider + zetetic agents | Aider applies diffs; before commit, zetetic agents verify the change matches a refusal-condition policy |
| Claude Code + zetetic | Vanilla Claude Code provides subagent orchestration; zetetic provides 118 agent definitions (in zetetic's "agent-as-reasoning-pattern" sense — see disambiguation card above) plus the commit-time gate layer |
| Continue + zetetic | Continue does codebase Q&A; zetetic agents handle the reasoning when an answer requires multi-step methodology |

Zetetic is built ON TOP OF Claude Code, not as an alternative. If you don't use Claude Code, zetetic doesn't run for you. The [`zetetic-checker`](../tools/zetetic-checker.sh) is one piece that runs anywhere as a standalone bash script — installable as a git pre-commit hook regardless of which AI assistant you use, but it only checks the source-citation rules (UNSOURCED keywords, MAGIC_NUMBER floats, TODO_NO_REF), not the agent reasoning layer.

---

## What zetetic is not

To prevent the inverse category errors:

- **Not an autonomous agent framework.** Cline / AutoGPT / CrewAI are autonomous executors. Zetetic is a methodology + enforcement layer for HUMAN-supervised AI sessions.
- **Not a chat UI.** Claude Code, Cursor, Continue, ChatGPT — these are interfaces. Zetetic is what runs THROUGH the interface when you use Claude Code.
- **Not a model.** GPT-5, Claude, Llama — these are models. Zetetic provides reasoning-procedure prompts and hooks that work with any model that Claude Code supports (Opus, Sonnet, Haiku).
- **Not a benchmark suite.** No metric here proves zetetic outperforms a baseline. The system's value is procedural and qualitative — sourced commits, documented refusals, structural-cause ADRs. You measure it by reading what it produces, not by a leaderboard.

---

## When NOT to use zetetic

Honest answer to the inverse question:

- **Greenfield prototypes where speed > rigor.** The hooks add friction by design. If you're sprinting through a hackathon prototype, the friction is wrong-shaped.
- **Personal scripts where source-citing every constant is overhead.** `permissive` profile exists for this case, but if every commit you make is a personal script, the system isn't earning its setup cost.
- **Outside Claude Code.** The orchestration depends on Claude Code's hook system. The standalone pieces ([`zetetic-checker`](../tools/zetetic-checker.sh), the pre-commit hook, the agents as raw markdown) work elsewhere — but the integrated experience is Claude Code-specific.

If your situation matches any of these, use the tool whose question matches your situation. We're not in your way.

---

## Final framing

**Read your row in the question table at the top.** Pick the tool that answers your actual question. If you also need claim-to-source traceability and commit-time epistemic enforcement, add zetetic to whatever else you use.

The four pillars (logical / critical / rational / essential) are the **lens** zetetic adds within its specific game (epistemic enforcement on reasoning-procedure agents in Claude Code), not a competitor's product spec. You can apply them as a discipline to any AI workflow without zetetic — zetetic's distinction is that it ships them as a commit-time gate within its game, not that other tools fail to support them within theirs.
