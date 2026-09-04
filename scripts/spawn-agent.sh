#!/usr/bin/env bash
# Spawn a zetetic agent as a standalone Claude Code session in an isolated git worktree.
#
# Usage:
#   scripts/spawn-agent.sh --contract <path> <agent-name> [task-description]
#
# Examples:
#   scripts/spawn-agent.sh --contract /tmp/c.json engineer "Fix the auth bug in login.py"
#   scripts/spawn-agent.sh --contract /tmp/c.json architect             # interactive REPL
#
# What it does:
#   0. Validates the delegation contract via tools/delegation_contract.py
#      (schema + ownership-overlap check) BEFORE any git or filesystem
#      mutation. Missing, malformed, or overlapping contracts are denied
#      with a non-zero exit and NO worktree is created. This is the
#      HC-ZETETIC-004 fail-closed precondition gate — see
#      schemas/delegation-contract.schema.yaml for the contract shape.
#   1. Resolves the agent file (agents/<name>.md) and strips YAML frontmatter.
#   2. Registers an active-contract lock (so a concurrent, overlapping
#      delegation is denied by step 0 while this one runs) and creates a git
#      worktree at ../<repo>-<agent>-<timestamp> on a new branch.
#   3. Launches `claude` there with:
#        --append-system-prompt  <agent body>   (installs the agent persona)
#        --permission-mode bypassPermissions    (no interactive approval prompts)
#      If a task is passed, runs headless with -p; otherwise drops into the REPL.
#   4. On exit (success, failure, or signal) releases the active-contract lock.
#
# Requirements: `claude` CLI on PATH, `git` >= 2.5, `python3` (contract validator).

set -euo pipefail

usage() {
  echo "usage: $0 --contract <path> <agent-name> [task]" >&2
  exit 2
}

CONTRACT=""
AGENT=""
declare -a REST=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --contract)
      [[ $# -ge 2 ]] || usage
      CONTRACT="$2"
      shift 2
      ;;
    --contract=*)
      CONTRACT="${1#--contract=}"
      shift
      ;;
    *)
      if [[ -z "$AGENT" ]]; then
        AGENT="$1"
      else
        REST+=("$1")
      fi
      shift
      ;;
  esac
done
TASK="${REST[*]:-}"

[[ -n "$AGENT" ]] || usage

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"

# Target project = current working directory's git root (the repo you want the
# agent to work ON), not this subagents repo.
TARGET_REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TARGET_NAME="$(basename "$TARGET_REPO")"

# ── Step 0: fail-closed contract validation — runs BEFORE any mutation ───────
# HC-ZETETIC-004: "A malformed or conflicting delegation will launch and
# mutate state before the system surfaces its missing authority, ownership
# conflict, or unverifiable completion contract." Nothing below this block
# may create a worktree, branch, process, or remote change until validation
# has explicitly returned "launch".
if [[ -z "$CONTRACT" ]]; then
  echo "deny: no delegation contract supplied (--contract <path> is required)" >&2
  exit 1
fi
if [[ ! -f "$CONTRACT" ]]; then
  echo "deny: contract file not found: $CONTRACT" >&2
  exit 1
fi

PYTHON3="$(command -v python3 || true)"
if [[ -z "$PYTHON3" ]]; then
  # Validator unavailable → fail closed, never degrade to the free-form launch path.
  echo "deny: python3 not found — contract validator unavailable, refusing to launch" >&2
  exit 1
fi

VALIDATOR_OUT="$("$PYTHON3" "$REPO_ROOT/tools/delegation_contract.py" "$CONTRACT" --repo-root "$TARGET_REPO" 2>&1)"
VALIDATOR_RC=$?
if [[ $VALIDATOR_RC -ne 0 ]]; then
  echo "deny: delegation contract rejected" >&2
  echo "$VALIDATOR_OUT" >&2
  exit 1
fi

CONTRACT_AGENT="$("$PYTHON3" -c "import json,sys; print(json.load(open(sys.argv[1]))['agent'])" "$CONTRACT")"
if [[ "$CONTRACT_AGENT" != "$AGENT" ]]; then
  echo "deny: contract declares agent '$CONTRACT_AGENT' but spawn requested '$AGENT'" >&2
  exit 1
fi
PUSH_AUTHORITY="$("$PYTHON3" -c "import json,sys; print(json.load(open(sys.argv[1]))['push_authority'])" "$CONTRACT")"

echo "→ contract accepted: agent=$CONTRACT_AGENT push_authority=$PUSH_AUTHORITY" >&2

# Resolve agent file: check agents/<name>.md first, then agents/genius/<name>.md
AGENT_FILE="$REPO_ROOT/agents/$AGENT.md"
if [[ ! -f "$AGENT_FILE" ]]; then
  AGENT_FILE="$REPO_ROOT/agents/genius/$AGENT.md"
fi

if [[ ! -f "$AGENT_FILE" ]]; then
  echo "error: agent not found: $AGENT" >&2
  echo "" >&2
  echo "team agents:" >&2
  ls "$REPO_ROOT/agents"/*.md 2>/dev/null | xargs -I{} basename {} .md | sed 's/^/  /' >&2
  echo "" >&2
  echo "genius agents:" >&2
  ls "$REPO_ROOT/agents/genius"/*.md 2>/dev/null | grep -v INDEX | xargs -I{} basename {} .md | sed 's/^/  genius\//' >&2
  exit 1
fi

# Strip the YAML frontmatter (everything between the first two `---` lines).
AGENT_BODY="$(awk 'BEGIN{f=0} /^---$/{f++; next} f>=2{print}' "$AGENT_FILE")"

STAMP="$(date +%Y%m%d-%H%M%S)"
WORKTREE="$TARGET_REPO/../${TARGET_NAME}-${AGENT}-${STAMP}"
BRANCH="agent/${AGENT}/${STAMP}"
LOCK_NAME="${AGENT}-${STAMP}"

# ── Step 2: register the active-contract lock, then mutate ───────────────────
LOCK_PATH="$("$PYTHON3" -c "
import sys
sys.path.insert(0, '$REPO_ROOT/tools')
import delegation_contract as dc
from pathlib import Path
contract = dc.validate(Path('$CONTRACT'), Path('$TARGET_REPO'))
print(dc.register_active(contract, '$LOCK_NAME', Path('$TARGET_REPO')))
")"

release_lock() {
  "$PYTHON3" -c "
import sys
sys.path.insert(0, '$REPO_ROOT/tools')
import delegation_contract as dc
from pathlib import Path
dc.release_active(Path('$LOCK_PATH'))
" 2>/dev/null || true
}
trap release_lock EXIT

echo "→ creating worktree: $WORKTREE (branch $BRANCH)"
git -C "$TARGET_REPO" worktree add -b "$BRANCH" "$WORKTREE"

cd "$WORKTREE"

echo "→ launching claude as '$AGENT' (permissions bypassed)"

# Set MEMORY_AGENT_ID so memory-tool.sh audit log and ACL use the correct
# identity. AGENT is the slug (basename of the agent file without .md).
# Identity MUST come from the spawn site, not the subagent: the subagent
# cannot forge its own id.
export MEMORY_AGENT_ID="$AGENT"
export DELEGATION_PUSH_AUTHORITY="$PUSH_AUTHORITY"

if [[ -n "$TASK" ]]; then
  claude \
    --permission-mode bypassPermissions \
    --append-system-prompt "$AGENT_BODY" \
    -p "$TASK"
else
  claude \
    --permission-mode bypassPermissions \
    --append-system-prompt "$AGENT_BODY"
fi
