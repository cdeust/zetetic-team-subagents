# Spawn Agent in Worktree

Spawn an agent as a standalone Claude Code session in an isolated git worktree.

## Instructions

1. Parse arguments: the first word is the agent name, the rest is the task description.
   Example: `/agent-spawn engineer Fix the auth bug in login.py`

2. Validate the agent exists by checking `agents/<name>.md` or `agents/genius/<name>.md`.

3. Build a delegation contract (JSON, per `schemas/delegation-contract.schema.yaml`)
   declaring, at minimum: `agent`, `target_repo`, `owned_paths`, `excluded_paths`,
   `worktree_policy`, `push_authority`, `handback_artifacts`, `acceptance_oracle`,
   `model`, `tool_grant`, `checkpoint_policy`. Write it to a temp file. This is
   mandatory — `scripts/spawn-agent.sh` refuses to create a worktree without a
   valid contract (HC-ZETETIC-004).

4. Run: `scripts/spawn-agent.sh --contract <contract-path> <agent-name> "<task>"`

5. Report the worktree path and branch name to the user.

6. If no task is provided, spawn in interactive REPL mode (no `-p` flag).

$ARGUMENTS
