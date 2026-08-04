---
name: codebase-intelligence
description: "ai-architect-mcp-codebase MCP workflow: analyze_codebase bootstrap, qualified-name syntax, per-tool usage table, graceful degradation"
read_when: "First use of the property-graph MCP tools in a session"
audience: team agents — loaded on demand via Read, never at spawn
---

**Optional MCP server: `ai-architect-mcp-codebase`** (from [`ai-architect-mcp-codebase`](https://github.com/cdeust/ai-architect-mcp-codebase)). When configured in `.mcp.json` or `~/.claude/settings.json`, the agent gains property-graph intelligence over Rust/Python/TypeScript codebases. Prefer these MCP tools to manual `Grep`/`Glob`/`Read` traversal — they return structured cross-file truth instead of pattern matches.

**Workflow (verified by smoke test 2026-04-17):** start with `analyze_codebase(path, output_dir)`; the response contains `graph_path` — capture it and pass it to every subsequent tool. Qualified names follow `<file_path>::<symbol_name>` (e.g., `src/main.rs::handle_tool_call`). Cross-file resolution rate is highest on multi-file real codebases; tiny single-file fixtures may return `resolution_rate: 0.00` with empty caller/import lists — this is a fixture limitation, not a tool bug.

| Tool | Use when |
|---|---|
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__analyze_codebase` | Task start, fresh repo. One-shot end-to-end indexing → returns layer graph, communities, entry points. Preferred over inferring layers from directory names. |
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__get_symbol` | Looking up a function, class, or type by qualified name. Returns definition + file + line + community + cross-references. Replaces `Grep` for known symbols. |
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__get_impact` | Root-cause analysis + before any non-trivial Edit. Returns blast radius one hop out — reverse dependencies only (callers, importers, users, implementors), NOT transitive and NOT test-aware (source: `impact.rs:177-216`, single reverse-edge match per call, no recursion, no test-entry-point correlation). To go deeper, follow the response's `next_steps` hints and re-call `get_impact` on a returned `callers[].qualified_name` — iteration is the caller's responsibility, not the tool's. Each result is qualified `exact` or `lower-bound` (`lower-bound` when dynamic dispatch or foreign callers make the count incomplete — source: `epistemic.rs:35-49`); treat `lower-bound` as a floor. Mandatory before editing a load-bearing function (mandatory at High stakes); for a deep call chain, budget multiple hops. |
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__search_codebase` | Hybrid BM25 + sparse TF-IDF + RRF search. Use for "where is X handled?" when the symbol name is unknown. Faster and more accurate than `grep -r`. |
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__get_processes` | Tracing execution flow from an entry point (request handler, job runner, CLI command). Replaces hand-following call chains. |
| `mcp__plugin_ai-architect-mcp-codebase_ai-architect__detect_changes` | Verification. Run AFTER Edits to confirm no unintended impact outside the planned blast radius. |

**Graceful degradation:** if the MCP server is not configured, fall back to `Glob`/`Grep`/`Read`. The MCP layer is intelligence on top of file I/O, not a replacement for it. Never block on MCP absence.
