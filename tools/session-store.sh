#!/usr/bin/env bash
# session-store.sh — Save/load session context
#
# Usage:
#   tools/session-store.sh save "<context summary>"
#   tools/session-store.sh load
#
# Stores context in
#   ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/session-cache/<sha256(toplevel)[0:16]>.json
# one file per working tree (git toplevel, or the physical pwd outside git).
# The cache lives under the user's Claude config dir and never inside the
# working repository: a file written there is untracked, and a worktree manager
# refuses to delete a worktree that holds an untracked file.
# (Cortex integration is handled by Claude directly via MCP; this is the
# fallback for non-Cortex environments.)
# Exit codes: 0 success, 1 error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)"
if command -v sha256sum >/dev/null 2>&1; then
  TREE_KEY="$(printf '%s' "$REPO_ROOT" | sha256sum | cut -c1-16)"
else
  TREE_KEY="$(printf '%s' "$REPO_ROOT" | shasum -a 256 | cut -c1-16)"
fi
CACHE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/session-cache"
CACHE_FILE="$CACHE_DIR/$TREE_KEY.json"
ACTION="${1:-}"; CONTEXT="${2:-}"

case "$ACTION" in
  save)
    [[ -z "$CONTEXT" ]] && { echo "usage: $0 save \"<context>\"" >&2; exit 1; }
    mkdir -p "$CACHE_DIR"
    cat > "$CACHE_FILE" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "branch": "$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')",
  "last_commit": "$(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')",
  "context": $(echo "$CONTEXT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo "\"$CONTEXT\"")
}
EOF
    echo "Session saved to $CACHE_FILE" ;;

  load)
    if [[ -f "$CACHE_FILE" ]]; then
      cat "$CACHE_FILE"
    else
      echo "No cached session found. Use Cortex recall for persistent memory."
      exit 1
    fi ;;

  *) echo "usage: $0 <save|load> [context]" >&2; exit 1 ;;
esac
