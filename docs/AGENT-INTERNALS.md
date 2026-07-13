# Agent file shape and internals

Every agent ships as a single Markdown file with YAML frontmatter. Slim frontmatter keeps cumulative description tokens across all 118 agents under Claude Code's startup cap (~12.6k tokens, was 28k in v2.12.0). Rich routing detail lives in body sections, loaded only when the agent is invoked.

## File shape (current — v2.13.0+)

```yaml
---
name: dijkstra
description: "Proactively enforce correctness discipline when..."   # 1 sentence — routing-discriminating
when_to_use: "When a program's correctness cannot be established..." # 1 clause — trigger
model: opus
effort: high
shapes: [proof-and-program-together, locality-of-reasoning, ...]
tools: [Read, Edit, Write, Bash, Glob, Grep, WebFetch, WebSearch]
memory_scope: genius   # team agents: <slug>; genius agents: "genius" (shared scope, per-slug subpath)
---

<identity>...</identity>

<routing>
**When to use this agent (full guidance — pairings, triggers, examples,
distinct-from-X clauses; loaded only when the agent is invoked):**
[every word from the original verbose `when_to_use`, preserved here]
</routing>

<revolution>...</revolution>           <!-- genius template -->
<domain-context>...</domain-context>   <!-- team template -->

<memory>
[Eco-template memory block — scope, three-command distinction, replica
 invariant, persist guidance, common mistakes]
</memory>

<canonical-moves>...</canonical-moves>
<refusal-conditions>...</refusal-conditions>
<blind-spots>...</blind-spots>

<codebase-intelligence>
[Optional MCP server `automatised-pipeline` tool table + workflow; graceful
 degradation when the server is absent.]
</codebase-intelligence>
```

## Why this shape

The orchestrator routes based on frontmatter — a sentence is enough. The invoked agent reads its full body. This separates **routing cost** (paid every session) from **methodology cost** (paid only when used), aligning with Claude Code's startup token budget while preserving every word of the canonical moves and procedure depth.

## Frontmatter fields

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | The agent slug; matches the filename and `MEMORY_AGENT_ID` |
| `description` | yes | One-sentence routing signal; appears in the agent picker |
| `when_to_use` | yes | One-clause trigger; helps the orchestrator pick |
| `model` | yes | `opus` / `sonnet` / `haiku` — overridable via `~/.claude/zetetic-agent-models.json` |
| `effort` | yes | `low` / `medium` / `high` / `max` — reasoning-token budget |
| `shapes` | genius only | Problem-shape labels matched by the shape-router |
| `tools` | yes | Subset of `Read, Edit, Write, Bash, Glob, Grep, WebFetch, WebSearch, Agent` |
| `memory_scope` | yes | Maps to `scope-registry.json` for ACL — team agents use their slug; all genius agents use `genius` |

## Body sections

| Section | Required for | Purpose |
|---|---|---|
| `<identity>` | both | One-paragraph self-statement |
| `<routing>` | both | Full routing guidance — pairings, triggers, distinct-from-X |
| `<revolution>` | genius | The reasoning-pattern's epistemological move |
| `<domain-context>` | team | The role's working domain |
| `<memory>` | both | Eco template — `view /memories/<scope>/` first; persist WHY-level decisions; respect ACL |
| `<canonical-moves>` | both | The 5 numbered moves the agent applies |
| `<refusal-conditions>` | both | When the agent declines and what artifact it produces instead |
| `<blind-spots>` | both | Self-documented limits |
| `<codebase-intelligence>` | optional | MCP graph-tool integration when `ai-automatised-pipeline` is attached |

## Adding a new agent

1. **Pick the slug** — must be unique across `agents/*.md` and `agents/genius/*.md`. Filename = `<slug>.md`.
2. **Pick the scope:**
   - Team agent: add an entry to [`memory/scope-registry.json`](../memory/scope-registry.json) with `owners: ["<slug>", "_user"]`
   - Genius agent: use `memory_scope: genius` (shared scope, per-slug subpath convention `/memories/genius/<slug>/`)
3. **Use the templates:**
   - Team body: [`memory/templates/agent-memory-block.team.md`](../memory/templates/agent-memory-block.team.md) — substitute `{{scope}}` and `{{agent_slug}}`
   - Genius body: [`memory/templates/agent-memory-block.genius.md`](../memory/templates/agent-memory-block.genius.md) — substitute `{{agent_slug}}`
4. **Run the auditor:**
   ```bash
   bash tools/agent-definition-auditor.sh
   ```
   16 structural checks. Must exit 0.
5. **Run the test suite:**
   ```bash
   bash scripts/test-memory-e2e.sh
   bash scripts/test-agent-id-propagation.sh
   ```
6. **Submit a PR** — see CONTRIBUTING.md (TODO).

## Refactorer's quick-extraction commands

For mechanical agent-file modifications:

```bash
# extract slug from filename
slug=$(basename agents/genius/feynman.md .md)

# extract frontmatter
awk '/^---$/{f++; next} f==1{print}' agents/genius/feynman.md

# extract body (everything after second ---)
awk 'BEGIN{f=0} /^---$/{f++; next} f>=2{print}' agents/genius/feynman.md

# verify YAML
python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]).read().split("---")[1])' agents/genius/feynman.md
```

## Counting INDEX.md problem-shape rows

The README claims a count of problem-shape triggers. To re-verify:

```bash
python3 - <<'PY'
data, sep, hdr = 0, 0, 0
with open("agents/genius/INDEX.md") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("- ") and c for c in cells if c):
            sep += 1
        elif any(h in cells for h in ("Shape", "Pattern", "Trigger", "Agent")):
            hdr += 1
        else:
            data += 1
print(f"data rows: {data}")
print(f"separators: {sep}")
print(f"headers: {hdr}")
PY
# Last verified count: 654 data rows on 2026-04-25.
```
