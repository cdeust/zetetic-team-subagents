#!/usr/bin/env bash
# post-commit-lab-notebook.sh — Prompt for lab notebook entry after commit during research session
# Lightweight check: if research/NOTEBOOK.md exists, remind to log the commit.
# Advisory PostToolUse hooks must fail open.  The command may target a repo via
# a tool workdir or `git -C` while the hook process itself starts elsewhere.
set -uo pipefail

# Command guard: only fire after git commit (matcher: "Bash" fires on ALL Bash calls)
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
# Match the git SUBCOMMAND (commit|push) at a command position only: line start or
# right after a shell separator (; & | ( {), then optional global flags (-x tokens,
# each optionally followed by one non-flag arg, e.g. -C /path), then the verb as a
# whole word NOT followed by '-' (excludes commit-tree/commit-graph, committed/pushed)
# and NOT inside an echo/quoted string or a --grep=... value. source: audit finding R1.
ZT_GIT_VERB_RE='(^|[;&|({])[[:space:]]*((sudo|command|env)[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*([^[:space:];&|({]*/)?git[[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*(commit|push)([[:space:];&|)<>]|$)'
if ! printf '%s' "$BASH_CMD" | grep -qE "$ZT_GIT_VERB_RE" 2>/dev/null; then exit 0; fi

HOOK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/git-context.sh
source "$HOOK_DIR/lib/git-context.sh"
if ! REPO_ROOT="$(zt_resolve_repo_root "$HOOK_INPUT" "$BASH_CMD")"; then
  exit 0
fi
NOTEBOOK="$REPO_ROOT/research/NOTEBOOK.md"
SESSION_FILE="$REPO_ROOT/research/.session.json"

# Only act if a research session is active
[[ ! -f "$NOTEBOOK" ]] && exit 0
[[ ! -f "$SESSION_FILE" ]] && exit 0

# Get the commit info
COMMIT_SHA="$(git -C "$REPO_ROOT" log --format='%h' -1 2>/dev/null || echo 'unknown')"
COMMIT_MSG="$(git -C "$REPO_ROOT" log --format='%s' -1 2>/dev/null || echo 'unknown')"

# Extract current research question from session
QUESTION=""
if command -v python3 &>/dev/null; then
  QUESTION=$(python3 -c "
import json, sys
try:
    d = json.load(open('$SESSION_FILE'))
    print(d.get('question', ''))
except: pass
" 2>/dev/null)
fi

echo ""
echo "=== Research Session Active ==="
echo "Commit: $COMMIT_SHA — $COMMIT_MSG"
[[ -n "$QUESTION" ]] && echo "Research question: $QUESTION"
echo ""
echo "Consider adding a lab notebook entry linking this commit to your current hypothesis:"
echo "  /research-notebook add \"<what this commit tests or changes>\" --commit $COMMIT_SHA"
echo ""
