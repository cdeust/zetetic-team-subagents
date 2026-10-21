---
name: memory-protocol
description: "Three memory retrieval surfaces (view / search / cortex:recall), the replica invariant, and common memory mistakes"
read_when: "Before your first memory search in a session; when a recall returns nothing or looks stale"
audience: delegated agents — loaded on demand via Read, never at spawn
---

## 3 — Three retrieval surfaces — know which to reach for

| Surface | Command | Behaviour | When to use |
|---|---|---|---|
| `view` | `tools/memory-tool.sh view <path>` | Returns exact bytes or directory listing for the path given. Deterministic. | You know the file or directory path. First action every session. |
| `search` | `tools/memory-tool.sh search "<query>" --scope <scope>` | Deterministic full-text grep across all files in the scope. Line-exact matches only. | You remember a concept or keyword but not the file. |
| `cortex:recall` | MCP tool — invoke directly, NOT via memory-tool.sh | Semantic similarity ranking. Non-deterministic across index updates. Eventually consistent. | You need conceptual retrieval ("what do I know about X?") and exact text is unknown. |
| `semantic-layer` | `tools/semantic-layer.sh query "<topic>"` | Query-indexed table of contents over Cortex: one entry per topic with sourced facts, gaps, and Cortex pointers. Deterministic substring/alias match. | You are about to **work a topic** and want "have we researched this, and what did we conclude?" before spending tokens on ingest. |

**Never alias these.** `view` is not search; `search` is not semantic recall; the `semantic-layer` is the topic index over the others. Confusing them returns wrong results silently.

---

## 4 — Semantic layer protocol — recall before ingest, record after

The semantic layer (`memory/semantic-layer.yaml`, schema in `memory/semantic-layer.schema.yaml`) is
the query-keyed learn loop: it makes an agent **faster and more complete on every revisit of a topic**.
It indexes Cortex — full content lives in Cortex (via `cortex_id`), the YAML is the small readable index.

- **Before ingesting a non-trivial topic:** run `tools/semantic-layer.sh query "<topic>"`. A fresh HIT
  means the work is already done — load the facts and follow `pointers.cortex_memories`. Do not re-ingest.
- **After researching a topic:** `cortex remember` the facts, then `… | tools/semantic-layer.sh record`
  with the Cortex ids as pointers. Record what you could NOT find as `gaps` (the next ingest backlog)
  and how to query better as `query_suggestions`. **Every fact must carry a `source` (§8)** — the
  validator rejects unsourced claims.
- **Full procedure:** the `semantic-ingest-loop` skill (`skills/research/semantic-ingest-loop.md`).

---

## 5 — Replica invariant

- **Local FS is authoritative.** A successful `create` or `str_replace` is durable immediately.
- **Cortex is an eventually-consistent replica.** It is written asynchronously via the `.pending-sync` queue.
- **Do not re-read Cortex to verify a local write.** If `tools/memory-tool.sh create` returned `"File created successfully at: <path>"`, the file exists. No reconciliation needed.
- Cortex write failures do NOT fail local operations. If `cortex:recall` returns stale or absent results after a local write, this is expected — the sync queue may not have drained yet.

---

## Common mistakes to avoid

- **Skipping the preamble `view`.** Resuming mid-task without checking memory causes duplicated work and lost state.
- **Writing code blocks as memory.** Memory files exceeding 100 KB are rejected. Code belongs in the codebase; decisions belong in memory.
- **Using `cortex:recall` when you know the path.** Semantic search is slower and non-deterministic. Use `view` first.
- **Writing to `/memories/lessons/` directly.** ACL will reject it. Propose lessons through the delegating session.
- **Treating a Cortex miss as evidence the memory doesn't exist.** Cortex sync may be pending. If `cortex:recall` returns nothing, run `tools/memory-tool.sh view /memories/<scope>/` before concluding the memory is absent.
