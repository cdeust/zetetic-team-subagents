#!/usr/bin/env bash
# pre-edit-layer-check.sh — ADVISORY layer-boundary reminder (NOT enforcement).
#
# This hook is a REMINDER, not a gate. It runs on Edit/Write of a core/ file and
# prints a note about the dependency rule (core may only depend inward). It does
# NOT block, and it does NOT authoritatively decide a layer violation: it has only
# the single edit in hand, not the whole module's import graph, so any verdict it
# emits is a heads-up to double-check — never a pass/fail.
#
# Real layer enforcement lives in tools/craftsmanship-checker.sh (the
# LAYER_VIOLATION detector), which runs at commit / CI time with the full file
# contents and a project-aware layer map. Treat that as the source of truth; this
# hook only nudges you toward it while you are still editing.
#
# FAIL-OPEN: missing tools, unparseable input, or any internal error exits 0.
set -euo pipefail

# --- A2: canonical bounded stdin read ---------------------------------------
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

# --- A10: extract file path — jq-primary, grep-fallback (trailing-anchored sed)
if command -v jq &>/dev/null; then
  FILE_PATH=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
else
  FILE_PATH=$(echo "$HOOK_INPUT" | grep -oE '"file_path":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"file_path":\s*"//' | sed 's/"$//' || echo "")
fi

[[ -z "$FILE_PATH" ]] && exit 0

# Only react when editing a core/ file; everything else is silent.
if ! echo "$FILE_PATH" | grep -qE '(^|/)core/' 2>/dev/null; then
  exit 0
fi

# --- A11(b): sharper advisory when the added text imports outward ------------
# Best-effort: parse the added content (new_string for Edit, content for Write)
# and look for inward-rule-breaking import targets. This is still ADVISORY — the
# authoritative check is tools/craftsmanship-checker.sh at commit/CI time.
if command -v jq &>/dev/null; then
  ADDED=$(echo "$HOOK_INPUT" | jq -r '.tool_input.new_string // .tool_input.content // empty' 2>/dev/null || echo "")
else
  ADDED=$(echo "$HOOK_INPUT" | grep -oE '"new_string":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"new_string":\s*"//' | sed 's/"$//' || echo "")
  [[ -z "$ADDED" ]] && ADDED=$(echo "$HOOK_INPUT" | grep -oE '"content":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"content":\s*"//' | sed 's/"$//' || echo "")
fi

# Match an import/use/require/from/include statement whose target path crosses an
# outward boundary (infrastructure / handlers / server). Restricted to lines that
# actually look like imports so prose mentioning the words does not trip it.
# A line qualifies when it (1) begins with an import-style keyword and (2) names
# an outward target as a delimited word — bounded by a non-word character (space,
# '/', '.', quote, '<', '>', ':', ';') or line end on each side. The optional
# middle group lets the target sit anywhere on the line (e.g. 'from app.infrastructure
# import x') while the mandatory leading boundary still catches 'from infrastructure'
# where the keyword's own separator is the delimiter. The leading-keyword anchor
# keeps prose that merely mentions the words ('infrastructure_count = 0') from tripping.
OUTWARD_IMPORT=$(echo "$ADDED" | grep -nE '^[[:space:]]*(import|from|use|require|include|#include)([^a-zA-Z0-9_].*)?[^a-zA-Z0-9_](infrastructure|handlers|server)([^a-zA-Z0-9_]|$)' 2>/dev/null | head -3 || true)

if [[ -n "$OUTWARD_IMPORT" ]]; then
  echo "NOTE: This edit to a core/ file adds an import that points OUTWARD (infrastructure/handlers/server)." >&2
  echo "Core must depend only on shared/ + the standard library; dependencies point inward." >&2
  echo "$OUTWARD_IMPORT" | while IFS= read -r hit; do
    echo "      added: ${hit}" >&2
  done
  echo "This is a reminder only — the authoritative check is tools/craftsmanship-checker.sh (LAYER_VIOLATION) at commit/CI time." >&2
else
  # No outward import spotted (or no content available) — generic inward-rule nudge.
  echo "NOTE: Editing a core/ file. Ensure no infrastructure/I/O imports are added; dependencies point inward." >&2
  echo "Advisory only — tools/craftsmanship-checker.sh enforces the layer rule (LAYER_VIOLATION) at commit/CI time." >&2
fi

exit 0
