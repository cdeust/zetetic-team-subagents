#!/usr/bin/env bash
# pre-commit-zetetic.sh — Enforce zetetic standard before commits
# Blocks commit if: invented constants, unsourced claims, or TODOs without difficulty-book refs.
set -euo pipefail

# Command guard: only fire on git commit (matcher: "Bash" fires on ALL Bash calls)
HOOK_INPUT=""
if ! [ -t 0 ]; then
  # Portable bounded stdin read. macOS ships NO 'timeout'/'gtimeout'; its
  # absence must NOT zero out the payload (that silently disables the hook — the
  # root cause of audit finding R1). Use the bound if present, else plain cat.
  _ZT="$(command -v timeout || command -v gtimeout || true)"
  if [ -n "$_ZT" ]; then
    HOOK_INPUT="$("$_ZT" 3 cat 2>/dev/null || true)"
  else
    HOOK_INPUT="$(cat 2>/dev/null || true)"
  fi
fi
if command -v jq &>/dev/null; then
  BASH_CMD=$(echo "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
else
  BASH_CMD=$(echo "$HOOK_INPUT" | grep -oE '"command":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"command":\s*"//' | sed 's/"$//' || echo "")
fi
# Match 'git commit'/'git push' only at a command position (A7): line start or
# after a shell separator (;&|({), then optional global flags (e.g. -C /path),
# then the verb as a whole word not followed by '-' (excludes commit-tree/
# commit-graph). Avoids false-triggers inside echo/quoted strings and --grep=.
GIT_EXECUTABLE_RE="['\"]?([^[:space:];&|({]*/)?git['\"]?"
GIT_VERB_RE='(^|[;&|({])[[:space:]]*((sudo|command|env)[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'"$GIT_EXECUTABLE_RE"'[[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*(commit|push)([[:space:];&|)<>]|$)'
if ! echo "$BASH_CMD" | grep -Eq "$GIT_VERB_RE" 2>/dev/null; then exit 0; fi

# Path resolution: CLAUDE_PLUGIN_ROOT → script-relative → git root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
TOOLS="${PLUGIN_ROOT}/tools"
[[ ! -d "$TOOLS" ]] && TOOLS="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Both packages share the same mechanical gate.
bash "$SCRIPT_DIR/gates-pre-commit.sh" <<<"$HOOK_INPUT"

"$TOOLS/difficulty-book-manager.sh" check 2>&1 || {
  echo "WARNING: Difficulty book has unaddressed hardest case." >&2
}

# Routing-table staleness: warn (don't block) when agent frontmatter changed
# without regenerating rules/agent-routing-table.md (R2 contract).
if [[ -x "$REPO_ROOT/scripts/generate-routing-table.py" ]]; then
  python3 "$REPO_ROOT/scripts/generate-routing-table.py" --check 2>&1 | grep -q 'up to date' || {
    echo "WARNING: rules/agent-routing-table.md is stale — run scripts/generate-routing-table.py and stage it." >&2
  }
fi

exit 0
