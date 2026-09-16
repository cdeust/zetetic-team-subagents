#!/usr/bin/env bash
# pre-push-fail-before.sh (zetetic-gates) — run tools/fail-before-checker.sh
# before a push issued through Claude Code. Rationale: docs/fail-before.md.
set -euo pipefail

# Command guard, identical to the sibling pre-commit hook: read the tool
# payload with a bounded wait, extract the Bash command, act only on git push.
HOOK_INPUT=""
if ! [ -t 0 ]; then
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

# The same push-verb regex the full plugin's pre-push-review.sh uses (A7).
GIT_PUSH_RE='(^|[;&|({])[[:space:]]*((sudo|command|env)[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*([^[:space:];&|({]*/)?git[[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?[[:space:]]+)*push([[:space:];&|)<>]|$)'
if ! echo "$BASH_CMD" | grep -qE "$GIT_PUSH_RE" 2>/dev/null; then exit 0; fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
GATE="${PLUGIN_ROOT}/tools/fail-before-checker.sh"
if [[ ! -x "$GATE" ]]; then
  echo "WARNING: fail-before-checker.sh not found — skipping the fail-before gate." >&2
  exit 0
fi

# Blocks (exit 2) only when the gate itself blocks, which it does for VACUOUS
# under ZETETIC_PROFILE=strict. Every other finding is relayed as a warning.
rc=0
output="$("$GATE" 2>&1)" || rc=$?
if [[ $rc -eq 1 ]]; then
  echo "BLOCKED: a new test passes against the old code (docs/fail-before.md)." >&2
  echo "$output" >&2
  exit 2
fi
if echo "$output" | grep -qE '^(VACUOUS|INCONCLUSIVE) '; then
  echo "$output" >&2
fi
exit 0
