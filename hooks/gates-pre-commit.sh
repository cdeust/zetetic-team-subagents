#!/usr/bin/env bash
# pre-commit-zetetic.sh (zetetic-gates) — enforce the zetetic + craftsmanship
# gates before commits issued through either supported host.
#
# Adapted from the full plugin's hooks/pre-commit-zetetic.sh: same command
# guard, same checker contract, minus the full plugin's repo-specific steps
# (difficulty-book check, routing-table staleness) which have no meaning in a
# gates-only install.
#
# Blocks commit (exit 2) if staged lines contain unsourced absolute claims or
# — under ZETETIC_PROFILE=strict — magic constants / orphan TODOs, or if a
# staged file violates the coding-standards §4 size limits.
set -euo pipefail

# Command guard: only fire on git commit (matcher "Bash" fires on ALL Bash calls)
HOOK_INPUT=""
if ! [ -t 0 ]; then
  # Portable bounded stdin read. macOS ships NO 'timeout'/'gtimeout'; its
  # absence must NOT zero out the payload (that silently disables the hook —
  # root cause of the full plugin's audit finding R1). Use the bound if
  # present, else plain cat.
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
# Match 'git commit' only at a command position: line start or after a shell
# separator (;&|({), then optional global flags (e.g. -C /path), then the verb
# as a whole word not followed by '-' (excludes commit-tree/commit-graph).
# Avoids false-triggers inside echo/quoted strings and --grep=.
# source: full plugin hooks/pre-commit-zetetic.sh (audit finding A7), verified
# by its tools/tests/hook-layer suite.
GIT_EXECUTABLE_RE="['\"]?([^[:space:];&|({]*/)?git['\"]?"
GIT_VERB_RE='(^|[;&|({])[[:space:]]*((sudo|command|env)[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'"$GIT_EXECUTABLE_RE"'[[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*(commit|push)([[:space:];&|)<>]|$)'
if ! echo "$BASH_CMD" | grep -Eq "$GIT_VERB_RE" 2>/dev/null; then exit 0; fi

# Path resolution: CLAUDE_PLUGIN_ROOT → script-relative
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
TOOLS="${PLUGIN_ROOT}/tools"

# Graceful degradation: if tools don't exist, skip checks (don't block commits)
if [[ ! -x "$TOOLS/zetetic-checker.sh" && ! -f "$TOOLS/zetetic-checker.sh" ]]; then
  echo "WARNING: zetetic-checker.sh not found — cannot run pre-commit checks." >&2
  exit 2
fi

# 1. Zetetic source discipline (UNSOURCED blocks at any profile).
output=$(bash "$TOOLS/zetetic-checker.sh" --staged 2>&1) || {
  echo "BLOCKED: Zetetic violations in staged files." >&2
  echo "$output" >&2
  exit 2
}

# Structural and prose checks read frozen index blobs, never unstaged edits.
if ! "$SCRIPT_DIR/run-python.sh" "$SCRIPT_DIR/lib/staged_checks.py" "$PLUGIN_ROOT" "$(pwd)"; then
  echo "BLOCKED: Craftsmanship or redaction validation failed on staged content." >&2
  exit 2
fi
exit 0
