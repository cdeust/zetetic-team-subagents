#!/usr/bin/env bash
# post-tool-error-routing.sh — Suggest diagnostic genius agent when a tool call fails
# Runs after PostToolUseFailure; reads context from stdin JSON.
set -euo pipefail

# Read hook context from stdin
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
[[ -z "$HOOK_INPUT" ]] && exit 0

# Extract the error from stdin JSON. Only the error text is extracted: routing
# scores the error string alone (see score_category below), so the tool name was
# computed and never consulted — removed rather than left as a dead subprocess.
if command -v jq &>/dev/null; then
  ERROR=$(echo "$HOOK_INPUT" | jq -r '.error // .tool_error // empty' 2>/dev/null || echo "")
else
  ERROR=$(echo "$HOOK_INPUT" | grep -oE '"error":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"error":\s*"//' | sed 's/"$//' || echo "")
fi

[[ -z "$ERROR" ]] && exit 0
ERROR_LOWER="$(echo "$ERROR" | tr '[:upper:]' '[:lower:]')"

# Sanitize the error before reflecting it into a /genius-invoke suggestion:
#   - collapse newlines/tabs to spaces (advisory text is a single line),
#   - strip the double-quotes that would break the quoted argument,
#   - bound the length so a multi-kilobyte stack trace doesn't flood the
#     suggestion. 160 chars is enough to identify the failure at a glance.
# source: measured on 2026-06-23 — a quoted shell argument must not contain an
# unescaped " ; truncation bound chosen to fit one terminal line.
ERROR_SAFE="$(printf '%s' "$ERROR" | tr '\n\r\t' '   ' | tr -d '"')"
if [ "${#ERROR_SAFE}" -gt 160 ]; then
  ERROR_SAFE="${ERROR_SAFE:0:160}…"
fi

suggest() {
  echo "Suggested genius agent: $1"
  echo "Reason: $2"
  echo "Invoke with: /genius-invoke $1 \"$ERROR_SAFE\""
}

# Word-anchored routing with score-all-then-emit-highest.
#
# Each category matches whole words only (grep -wE), so 'auth' no longer fires
# inside 'author', 'oom' inside 'zoom', 'import' inside 'important', etc. Every
# category is scored against the whole error string and the highest scorer wins;
# ties break by declaration order (first declared keeps the lead). This replaces
# first-match-wins, where category order silently decided routing.
#
# This is an ADVISORY suggestion only. Exit 0 regardless of the outcome.
score_category() {
  # $1 = word-anchored alternation; echo the number of matched lines.
  echo "$ERROR_LOWER" | grep -woE "$1" 2>/dev/null | sort -u | wc -l | tr -d ' '
}

best_agent=""
best_reason=""
best_score=0

consider() {
  # $1 score  $2 agent  $3 reason — keep strictly-greater (declaration-order tie-break).
  if [ "$1" -gt "$best_score" ]; then
    best_score="$1"
    best_agent="$2"
    best_reason="$3"
  fi
}

# Build / compilation errors
consider "$(score_category 'compile|build|syntax|parse|undefined|import|module|cannot find')" \
  "dijkstra" "Build/compile error — structured correctness analysis"

# Test failures
consider "$(score_category 'test|tests|assert|assertion|expect|mismatch|unequal')" \
  "fisher" "Test failure — experimental design and statistical reasoning"

# Timeout / performance
consider "$(score_category 'timeout|deadline|oom|exceeded|slow')" \
  "erlang" "Timeout/capacity issue — queuing theory and capacity planning"

# Permission / access errors
consider "$(score_category 'permission|denied|forbidden|eacces|chmod')" \
  "hamilton" "Permission error — defensive design and failure handling"

# Auth / credential errors
consider "$(score_category 'auth|unauthorized|401|403|token|credential|login|certificate')" \
  "rejewski" "Auth/credential error — reverse engineering and decipherment"

# Type / contract errors
consider "$(score_category 'type|cannot assign|incompatible|contract|interface|trait')" \
  "liskov" "Type/contract error — substitutability and composability analysis"

if [ -n "$best_agent" ]; then
  suggest "$best_agent" "$best_reason"
fi

# Advisory only — never block.
exit 0
