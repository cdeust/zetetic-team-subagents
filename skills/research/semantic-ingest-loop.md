---
name: semantic-ingest-loop
description: >
  Auto-ingest / auto-learn loop over the query-indexed semantic layer. Before working a
  topic, recall what is already known; ingest only the gaps; distill sourced facts; persist
  them (Cortex full content + semantic-layer.yaml index); then record outcome + gaps so the
  topic gets more complete on every visit. Replicates the firecrawl search-feedback loop,
  owned locally.
category: research
trigger: >
  When an agent starts working a non-trivial topic that future sessions will revisit; when
  "have we researched this before?" should be answered before spending tokens on ingest;
  when a research/investigation result is worth making cheaply recallable next time.
agents:
  - peirce
  - shannon
  - feynman
  - popper
  - ranganathan
  - mendeleev
shapes: [abductive-hypothesis, define-the-measure-first, two-independent-methods, falsifiability-gate]
input: A topic or question. The agent's domain. Optional acquisition budget (web/papers/code).
output: A validated semantic-layer.yaml entry keyed by the query, Cortex memories for full content, and recorded gaps that become the next ingest backlog.
zetetic_gate:
  logical: "The topic is normalized to a stable query_id before recall — same topic maps to the same key"
  critical: "Every stored fact carries a source (coding-standards §8); unsourced claims are dropped, not stored"
  rational: "Ingest depth is proportional to the gap — a HIT-and-fresh recall skips ingest entirely"
  essential: "On exit the entry records outcome + gaps; a topic never closes without its learn signal"
composes: [deep-research, literature-review, autoresearch-loop, lab-notebook]
aliases: [ingest-loop, auto-learn, semantic-recall, topic-memory]
hand_off:
  recall_hit_fresh: "(stop ingest) — load facts + pointers and proceed with the actual task"
  large_unknown_topic: "/deep-research — full end-to-end investigation, then return here to persist"
  claims_unverifiable: "record gap with status open; do NOT store an unsourced fact"
---

## Procedure

The loop is the firecrawl `search → verify → feedback` shape pointed at a **local, owned** index.
Tooling: `tools/semantic-layer.sh` (the YAML index) + `cortex remember/recall` (full content).

### Phase 0: Normalize (shannon + ranganathan)

1. **shannon: name the query.** Restate the topic as one natural-language question — the human key.
2. **ranganathan: derive the `query_id`.** A stable kebab-case slug. The same topic must always
   map to the same id, or recall misses and the topic forks. List 1–3 `aliases` (alternate framings).

### Phase 1: Recall (the "are we faster this time?" step)

3. **Query the semantic layer first.** `tools/semantic-layer.sh query "<topic>"`.
   - **HIT & `status: fresh`** → load `summary`, `facts`, and `pointers.cortex_memories`; follow the
     Cortex ids for depth via `cortex recall`. **Skip to Phase 5** (record only if you learned more).
   - **HIT & `stale`/`superseded`**, or **MISS** → continue to ingest.
4. **cortex recall** the same query for any unindexed prior memories (the YAML indexes Cortex, but
   Cortex may hold facts not yet indexed). Anything found seeds the entry.

### Phase 2: Ingest the gap (peirce — run several framings)

5. **peirce: multiple framings.** Recall improves markedly with diverse framings (firecrawl's
   recall trick). Run the `aliases` and sibling/rival angles, not one query. Route by source kind:
   - web → `WebSearch` / `WebFetch`   · papers → `/deep-research`, `/literature-review`
   - code → `ai-architect-mcp-codebase` (`search_codebase`, `query_graph`, `get_symbol`)
   - existing gaps from a prior visit ARE the priority backlog — ingest those first.

### Phase 3: Distill & verify (feynman + popper)

6. **feynman: distill to semantic units.** Each fact = one verifiable `claim` + its `source`
   (file:line, URL, paperId, benchmark path). No source → drop it (§8).
7. **popper: verify load-bearing claims at the source** before accepting (firecrawl's `read_paper`
   step) — read the actual passage; do not trust a snippet. Use `two-independent-methods` for
   high-stakes facts.

### Phase 4: Persist (dual write — Cortex stores, YAML indexes)

8. **cortex remember** each durable fact → returns a memory id. Full content lives here.
9. **Record the index entry.** Build the entry JSON (schema: `memory/semantic-layer.schema.yaml`),
   putting the Cortex ids in `facts[].cortex_id` and `pointers.cortex_memories`, then:
   `echo '<entry-json>' | tools/semantic-layer.sh record`. The tool validates and upserts by id.

### Phase 5: Feedback (the learn signal — never skip)

10. **Record outcome + gaps.** What you still could not find becomes `gaps` (firecrawl's
    `missingContent`); how to query better becomes `query_suggestions`:
    `echo '{"outcome":{...},"gaps":[...],"status":"fresh"}' | tools/semantic-layer.sh feedback <query_id>`.
11. **Set freshness.** Choose `ttl_days` / `revalidate_after` by volatility (fast-moving topic →
    short TTL; `watch: true` to have it surfaced for re-check). Stale entries resurface via
    `tools/semantic-layer.sh revalidate`.

## Output Format

```
## Semantic Ingest: [query]

### query_id: [slug]   status: [fresh|stale]   recall: [HIT-fresh | HIT-stale | MISS]

### Facts persisted (each sourced):
- [claim]  — [source]  (cortex: [id])

### Gaps recorded (next ingest backlog):
- [topic] — [status]

### Outcome: [good|partial|bad]   Revalidate after: [date]
### Query suggestion for next visit: [...]
```

## Invariants

- **Recall before ingest.** Phase 1 is the whole point — it is what makes the agent faster on the
  second visit. Never skip straight to ingest on a topic that might already be indexed.
- **The index is a table of contents, not the library.** Keep entries small; depth lives in Cortex.
  Do not paste multi-KB content into the YAML.
- **No unsourced facts.** The validator rejects them; so should you, before calling `record`.
- **A topic never closes without its learn signal.** Phase 5 is mandatory even on a clean HIT —
  if you learned nothing new, that itself is recordable (confirm freshness, close a gap).
