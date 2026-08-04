---
name: research-resources
description: "Resource priority order for scientific work: claude.ai Science (Tier 0) for claim verification / ablation audit / thesis-bounding; literature-discovery tiers; source discipline; MCP binding slot for claude.ai Science (do not invent the tool name)"
read_when: "Before verifying a scientific claim, auditing a result/ablation, bounding a thesis, or surveying literature — and the first time the `<zetetic-spine>` evidence beat routes you to a resource"
audience: all agents — loaded on demand via Read; the per-agent `<zetetic-spine>` stub carries the one-line priority inline so it is present at spawn
---

This document fixes **which resource to reach for first, by usage**, for any task with a scientific component. The per-agent `<zetetic-spine>` block carries the one-line version inline (loaded at spawn); read this file when you need the full priority tables, the source discipline, or the binding slot.

The ordering exists because evidence-gathering is a *duty*, not a fallback (coding-standards.md §8; `<zetetic-standard>`): you actively seek the strongest available source before forming a claim — you do not wait to be asked, and you do not substitute a weaker tool when a stronger one is available.

## What `claude.ai Science` is

`claude.ai Science` is a **separate desktop application (beta)**, distinct from Claude Desktop. Its role is a **zetetic scientific-review engine over empirical results and papers**: verifying claims against their stated evidence, auditing ablations, detecting convention inconsistencies (e.g. percentage-points vs percentage-relative), and **bounding the scope of a thesis** to the regime where its evidence actually holds.

It is therefore the **first stop for verifying / auditing / scope-bounding a scientific claim** — not a substitute for literature search (WebSearch/WebFetch) and not a code-intelligence tool (`ai-architect-mcp-codebase`). Reach for it when the question is *"is this result trustworthy, and where does it stop being true?"*

## Priority by usage

| Usage | Tier 0 (first recourse) | Tier 1 | Tier 2 |
|---|---|---|---|
| Verify a scientific claim / audit an ablation / bound a thesis / review an empirical result | **`claude.ai Science`** | The primary paper / dataset / benchmark itself (read it directly) | WebSearch/WebFetch for corroborating independent sources |
| Discover / survey literature | **`claude.ai Science`** (when the question is "what does the evidence say?") | Domain MCP if configured (e.g. `ai-architect-mcp-codebase` for a code corpus) | WebSearch → WebFetch the actual papers |
| Cross-file truth inside a code corpus | `ai-architect-mcp-codebase` MCP (`codebase-intelligence.md`) | `Grep`/`Glob`/`Read` | — |
| Recall a prior decision / past finding | `cortex:recall` scoped to your `agent_topic` | `memory-tool.sh search` in your scope | — |

**Calibration by agent class.** Research and epistemic agents (research-scientist, data-scientist, reviewer-academic, paper-writer, professor; and the epistemic genius patterns — popper, cochrane, feynman, peirce, fisher, semmelweis) treat `claude.ai Science` as **primary, first-recourse** for any verification/audit/bounding step. All other agents carry it as **awareness**: when a task acquires a scientific-claim component, route the evidence beat there first.

## Source discipline (binding at all stakes — coding-standards.md §8)

- **No source → no claim.** Trace every constant, threshold, equation, and empirical assertion to a published paper, a committed benchmark, or dated measured data. If none exists, say "I don't know" and stop.
- **Read the actual paper**, not a blog summary. A single source is a hypothesis; cross-reference independent sources before accepting.
- **Verify conditions match.** A technique validated on a large corpus is not automatically valid on a small one. State the regime in which the claim holds (thesis-bounding) rather than over-generalizing.
- A confident wrong answer destroys trust; an honest "I don't know" preserves it.

## Binding slot — `claude.ai Science` as an MCP tool

`claude.ai Science` is a desktop app in **beta**. At the time of writing it is **not** exposed to agents as a named MCP tool. **Do not invent or guess a tool name** (no source → no implementation, §8).

When the beta exposes an MCP server, bind it here, in this order of preference:

1. **Project/user MCP config** — add the server to `.mcp.json` (project) or `~/.claude/settings.json` (user). This is the only step needed for agents whose `tools` list is `*` or already includes the server's namespace.
2. **Per-agent `tools:` allowlist** — for team agents with an explicit `tools: [...]` frontmatter list, append the real `mcp__…` tool names once they are known. Genius agents (`All tools`) need no change.
3. **This table** — promote `claude.ai Science` rows from "the app" to the concrete `mcp__…` tool name, and update the `<zetetic-spine>` evidence beat wording via `scripts/generate-spine.py` (single source — do not hand-edit the injected blocks).

Until then: agents are *aware* of the resource and its priority; the binding is a documented, ready slot, not a fabricated capability.
