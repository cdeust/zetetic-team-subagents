#!/usr/bin/env python3
"""
Upgrade all agent/genius files with:
1. Model tiering (opus/sonnet/haiku by role)
2. Token budget protocol (200K limit with checkpoint/restart)
3. Scope-update via system prompt reinjection (Opus 4.8)
"""
import os
import re

AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agents")

# Model assignments by agent name
# opus  = planning / deep reasoning
# sonnet = analysis / review
# haiku  = implementation / routine
OPUS_AGENTS = {
    # team
    "orchestrator", "architect",
    # genius (all 98 — handled separately via is_genius flag)
}
SONNET_AGENTS = {
    "code-reviewer", "security-auditor", "reviewer-academic",
    "research-scientist", "data-scientist", "experiment-runner",
    "paper-writer", "ux-designer",
}
HAIKU_AGENTS = {
    "engineer", "test-engineer", "refactorer", "devops-engineer",
    "dba", "frontend-engineer", "mlops", "latex-engineer",
    "professor",
}

TOKEN_BUDGET_SECTION = """\
<token-budget>
## Token Budget Protocol — 200K Hard Limit

Every agent session has a hard cap of **200,000 tokens** (context + output combined). This protocol prevents runaway sessions and preserves reasoning continuity across restarts.

### Checkpoint trigger
When your running estimate of tokens consumed reaches **~180,000**, you MUST checkpoint before continuing:

1. **Save state** — write all progress, open decisions, and remaining work to your memory subtree:
   ```bash
   MEMORY_AGENT_ID=<your-id> tools/memory-tool.sh create /memories/<scope>/<topic>/checkpoint.md "$(cat <<'EOF'
   ## Checkpoint <ISO-date>
   ### Completed
   - ...
   ### In progress
   - ...
   ### Remaining
   - ...
   ### Key decisions so far
   - ...
   EOF
   )"
   ```
2. **Signal the orchestrator** — end your response with:
   `CHECKPOINT — context cleared. Resume from /memories/<scope>/<topic>/checkpoint.md`
3. **On restart** — your absolute first act is always:
   ```bash
   MEMORY_AGENT_ID=<your-id> tools/memory-tool.sh view /memories/<scope>/
   ```
   then load your checkpoint before touching any other file or tool.

### Rules
- **Never exceed 200K tokens** in one session. Prefer multiple focused sessions of ≤150K each.
- **Memory is the persistent state** between sessions, not the context window.
- **Complex multi-step tasks** must be chunked into explicit sub-sessions upfront; record the chunk plan in memory before starting.
- **Token estimation**: count system prompt (~15K) + conversation history + your response budget. When in doubt, checkpoint early rather than late.
</token-budget>
"""

SCOPE_UPDATE_SECTION = """\
<scope-update>
## Scope Update via System Prompt Reinjection (Opus 4.8)

When task scope changes mid-execution — a constraint is discovered, the caller redirects, or the original framing is wrong — **do not patch the conversation context**. Use Opus 4.8 system prompt reinjection instead:

### Procedure
1. **Identify the delta**: what specifically changed about the task (added constraint, removed branch, redirected goal)?
2. **Compose the updated scope** as a concise system-level statement — not a user turn, not a clarification appended to the thread.
3. **Reinject** by treating the updated scope as the authoritative task description for all subsequent reasoning. The original conversation history is unchanged; the scope update lives in the system-prompt layer.
4. **Record the scope change** in your memory subtree:
   ```bash
   MEMORY_AGENT_ID=<your-id> tools/memory-tool.sh create /memories/<scope>/scope-history.md \
     "<ISO-date>: scope changed FROM '<original>' TO '<updated>' BECAUSE '<reason>'"
   ```

### When to trigger
- Mid-task discovery reveals the original task framing is incomplete or wrong.
- A sub-agent returns results that eliminate an entire planned branch.
- The caller explicitly redirects to a different sub-problem.
- A file, API, or design constraint rules out the planned approach entirely.

### What NOT to do
- Do not append the scope change as a user/assistant turn — this wastes context budget and pollutes conversation history.
- Do not silently abandon the original task — always record the scope delta in memory.
- Do not restart the whole session to handle a small scope change — reinjection handles incremental updates cheaply.
</scope-update>
"""


def get_model_for_agent(name: str, is_genius: bool) -> str:
    if is_genius:
        return "opus"
    if name in SONNET_AGENTS:
        return "sonnet"
    if name in HAIKU_AGENTS:
        return "haiku"
    return "opus"  # default for unlisted


def upgrade_file(path: str, name: str, is_genius: bool) -> bool:
    with open(path, "r") as f:
        content = f.read()

    original = content

    # 1. Update model in frontmatter
    new_model = get_model_for_agent(name, is_genius)
    content = re.sub(r"^model: \w+", f"model: {new_model}", content, flags=re.MULTILINE)

    # 2. Add token-budget section (before </output> or at end)
    if "<token-budget>" not in content:
        if "</output>" in content:
            content = content.replace("</output>", TOKEN_BUDGET_SECTION + "\n</output>", 1)
        else:
            content = content.rstrip() + "\n\n" + TOKEN_BUDGET_SECTION

    # 3. Add scope-update section (after token-budget, before </output>)
    if "<scope-update>" not in content:
        if "</output>" in content:
            content = content.replace("</output>", SCOPE_UPDATE_SECTION + "\n</output>", 1)
        else:
            content = content.rstrip() + "\n\n" + SCOPE_UPDATE_SECTION

    if content == original:
        return False

    with open(path, "w") as f:
        f.write(content)
    return True


def main():
    changed = 0
    skipped = 0

    # Team agents
    for fname in os.listdir(AGENTS_DIR):
        if not fname.endswith(".md"):
            continue
        name = fname[:-3]
        path = os.path.join(AGENTS_DIR, fname)
        if upgrade_file(path, name, is_genius=False):
            changed += 1
            print(f"  updated: agents/{fname}")
        else:
            skipped += 1

    # Genius agents
    genius_dir = os.path.join(AGENTS_DIR, "genius")
    for fname in os.listdir(genius_dir):
        if not fname.endswith(".md"):
            continue
        name = fname[:-3]
        path = os.path.join(genius_dir, fname)
        if upgrade_file(path, name, is_genius=True):
            changed += 1
            print(f"  updated: agents/genius/{fname}")
        else:
            skipped += 1

    print(f"\nDone: {changed} updated, {skipped} already up-to-date")


if __name__ == "__main__":
    main()
