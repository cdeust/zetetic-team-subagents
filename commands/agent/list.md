# List Available Agents

List the zetetic agents (genius reasoning patterns; the team-role agents were removed) with their roles and trigger conditions.

## Instructions

1. Run the agent catalog tool to list agents. Apply filters if the user specified any:
   - All agents: `tools/agent-catalog.sh --all`
   - Genius agents: `tools/agent-catalog.sh --genius`
   - By shape: `tools/agent-catalog.sh --genius --shape "$ARGUMENTS"`
   - By keyword: `tools/agent-catalog.sh --search "$ARGUMENTS"`

2. If the user asked about a specific problem (not an agent name), run `tools/shape-router.sh "$ARGUMENTS"` to find the matching genius agent(s) by problem shape.

3. Present results as a clean table. For genius agents, include the problem shapes they serve.

$ARGUMENTS
