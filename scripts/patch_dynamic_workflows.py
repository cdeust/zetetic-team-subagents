#!/usr/bin/env python3
"""
Patch 4: Add dynamic-workflow cost warning to all 117 agents.

Dynamic workflows (Claude Code research preview) spin up 10s–100s of parallel
subagents and should be treated as a last resort due to extreme token and cost
implications.

Changes:
1. Add <dynamic-workflows> warning section to every agent
2. Add a specific callout in orchestrator.md's parallelism section
"""
import os

AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agents")

DYNAMIC_WORKFLOWS_SECTION = """\
<dynamic-workflows>
## Dynamic Workflows — Use Sparingly (Last Resort)

Claude Code dynamic workflows (research preview) run 10s–100s of parallel subagents, check their work, and return a single synthesized result. They are powerful for extraordinarily large tasks but carry **severe token and cost implications**.

### Cost reality
- Each subagent is a full model invocation with its own context load.
- 100 parallel subagents at Sonnet 4.6 = 100× the per-turn cost, plus orchestration overhead.
- Token consumption compounds: every subagent loads the system prompt, tools, and context; nothing is shared.
- A single dynamic workflow run on a large codebase can consume millions of tokens in minutes.

### The rule: exhaust sequential and targeted parallel options first

Before triggering a dynamic workflow, confirm ALL of these are true:
1. The task genuinely cannot be decomposed into a small (≤5) set of targeted subtasks.
2. Manual fan-out via the `Agent` tool would require >20 independent agents to be useful.
3. The cost has been acknowledged by the user or the orchestrator has explicit budget authorization.
4. No simpler approach (grep, read, targeted search, sequential agents) can answer the question.

If even one of these is false: **do not use dynamic workflows**.

### When dynamic workflows ARE appropriate
- Finding bugs or patterns across a very large codebase (100+ files) where targeted search misses cross-file interactions.
- Large-scale refactors or migrations that genuinely affect every file.
- Stress-testing / adversarial verification at scale before a major release.
- Long-running work where hours of compute are authorized and budgeted.

### What to use instead (in order of preference)
1. **Read + Grep + targeted search** — covers 90% of codebase exploration.
2. **Agent tool with 2–5 focused subagents** — covers most parallel analysis needs.
3. **Sequential specialist agents** — orchestrator → architect → engineer chain.
4. **Dynamic workflows** — only when the above have been tried and are insufficient.

### Cost estimation before triggering
Always estimate before launching:
```
Estimated subagents: N
Avg context per subagent: ~X tokens
Model: <model>
Estimated cost: N × X × (price/MTok) ≈ $Y
```
If the estimate exceeds $5 for a single workflow run, require explicit user authorization before proceeding.
</dynamic-workflows>
"""

# Additional note to insert in orchestrator.md's parallelism section
ORCHESTRATOR_PARALLELISM_NOTE = """\

**Dynamic workflow warning (Move 3 addendum):** Dynamic workflows (100s of parallel subagents) are a last resort — not the default for parallelism. For most tasks, 2–5 targeted subagents via the `Agent` tool provide adequate parallelism at a fraction of the cost. See `<dynamic-workflows>` section for the decision gate.
"""

ORCHESTRATOR_PARALLELISM_ANCHOR = "**Do not fake parallelism.**"


def patch_file(path: str, name: str) -> bool:
    with open(path) as f:
        content = f.read()

    original = content

    # 1. Add <dynamic-workflows> section to all agents (after <effort-calibration> or at end)
    if "<dynamic-workflows>" not in content:
        if "</effort-calibration>" in content:
            content = content.replace(
                "</effort-calibration>",
                "</effort-calibration>\n\n" + DYNAMIC_WORKFLOWS_SECTION.rstrip(),
                1,
            )
        else:
            content = content.rstrip() + "\n\n" + DYNAMIC_WORKFLOWS_SECTION.rstrip() + "\n"

    # 2. Extra note in orchestrator's parallelism section
    if name == "orchestrator" and ORCHESTRATOR_PARALLELISM_NOTE.strip() not in content:
        if ORCHESTRATOR_PARALLELISM_ANCHOR in content:
            content = content.replace(
                ORCHESTRATOR_PARALLELISM_ANCHOR,
                ORCHESTRATOR_PARALLELISM_NOTE.rstrip() + "\n\n" + ORCHESTRATOR_PARALLELISM_ANCHOR,
                1,
            )

    if content == original:
        return False

    with open(path, "w") as f:
        f.write(content)
    return True


def main():
    changed = skipped = 0

    for fname in sorted(os.listdir(AGENTS_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(AGENTS_DIR, fname)
        if patch_file(path, fname[:-3]):
            changed += 1
            print(f"  patched: agents/{fname}")
        else:
            skipped += 1

    genius_dir = os.path.join(AGENTS_DIR, "genius")
    for fname in sorted(os.listdir(genius_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(genius_dir, fname)
        if patch_file(path, fname[:-3]):
            changed += 1
            print(f"  patched: agents/genius/{fname}")
        else:
            skipped += 1

    print(f"\nDone: {changed} patched, {skipped} skipped")


if __name__ == "__main__":
    main()
