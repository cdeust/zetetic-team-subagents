# Route Problem to Genius Agents

Analyze a problem description, find matching genius agent shapes, and recommend agents.

## Instructions

1. Take the problem description from $ARGUMENTS.

2. Run `tools/genius-invoker.sh route "$ARGUMENTS"` to grep INDEX.md for matching shapes.

3. Read `rules/agent-routing-table.md` (installed: `~/.claude/reference/agent-routing-table.md`) — the compact generated table of all 116 agents (name + shape keywords + one-line description, ~25KB). Match the problem against shape keywords and descriptions:
   - Exact shape name matches
   - Semantic matches where the problem structure fits a shape even without keyword overlap

   Do NOT Read `agents/genius/INDEX.md` (132KB) or full agent files to route. If you need a shape's trigger text or key move for a shortlisted candidate, grep INDEX.md for that shape name only: `grep -A1 '<shape-name>' agents/genius/INDEX.md`.

4. Rank recommendations by match quality. For each recommended agent (1-3 max), output:
   - **Agent name** and link to its file
   - **Matching shape(s)** with the trigger text from the targeted INDEX.md grep
   - **Why it matches** — connect the problem's structure to the shape's trigger
   - **Key move** — what the agent will do first

5. If multiple agents match, suggest a **composition sequence**: which agent to run first and why, what its output feeds into the next agent, and the expected combined insight. Reference `tools/genius-invoker.sh compose` for execution.

6. If no shapes match, say so clearly. Suggest the user try a standard team agent instead or rephrase the problem to expose its structural shape.

$ARGUMENTS
