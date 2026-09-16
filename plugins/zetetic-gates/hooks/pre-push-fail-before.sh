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
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}"
# Resolve event cwd and git -C/leading cd without evaluating shell input.
TARGET="$(printf '%s' "$HOOK_INPUT" | bash "$PLUGIN_ROOT/hooks/run-python.sh" \
  "$PLUGIN_ROOT/hooks/git-push-context.py")"
[ -n "$TARGET" ] || exit 0
if ! cd "$TARGET"; then
  echo "INCONCLUSIVE fail-before: push directory is unavailable: $TARGET" >&2
  exit 0
fi
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
if [[ $rc -ne 0 ]]; then
  echo "INCONCLUSIVE fail-before: checker exited $rc; inspect the diagnostic below." >&2
  echo "$output" >&2
  exit 0
fi
if echo "$output" | grep -qE '^(VACUOUS|INCONCLUSIVE) '; then
  echo "$output" >&2
fi
exit 0
