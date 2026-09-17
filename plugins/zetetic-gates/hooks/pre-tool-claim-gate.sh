#!/usr/bin/env bash
# pre-tool-claim-gate.sh — ADVISORY zetetic-claim reminder before Write/Edit.
#
# Runs on Edit/Write and prints a heads-up when the new content contains a
# named constant, tuning parameter, or in-comment algorithm claim with no
# provenance annotation. It only ever has the single edit's content in hand, so
# its findings are nudges, not verdicts.
#
# Authoritative MAGIC_NUMBER / source-discipline enforcement lives in
# tools/zetetic-checker.sh (runs at commit / CI with the staged diff and the
# project profile). Treat that as the source of truth; this hook is the
# low-noise edit-time subset that points you at it.
#
# FAIL-OPEN: missing tools, unparseable input, or any internal error exits 0.
# This hook NEVER blocks (it only prints WARNING lines).
set -euo pipefail

# --- A2: canonical bounded stdin read ---------------------------------------
HOOK_INPUT=""
if ! [ -t 0 ]; then
  # Portable bounded stdin read. macOS ships NO 'timeout'/'gtimeout'; its
  # absence must NOT zero out the payload (that silently disabled this hook —
  # the root cause of the audit's stdin finding). Use the bound if present,
  # else plain cat.
  _ZT="$(command -v timeout || command -v gtimeout || true)"
  if [ -n "$_ZT" ]; then
    HOOK_INPUT="$("$_ZT" 3 cat 2>/dev/null || true)"
  else
    HOOK_INPUT="$(cat 2>/dev/null || true)"
  fi
fi

# Extract file path from context
if command -v jq &>/dev/null; then
  FILE=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
else
  FILE=$(echo "$HOOK_INPUT" | grep -oE '"file_path":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"file_path":\s*"//' | sed 's/"$//' || echo "")
fi

VIOLATIONS=0

[[ -z "$FILE" ]] && exit 0

# Only check code files, skip markdown/config
case "$FILE" in
  *.md|*.json|*.yaml|*.yml|*.toml|*.lock|*.txt|*.csv) exit 0 ;;
esac

# Extract content from hook context (new_string for Edit, content for Write)
if command -v jq &>/dev/null; then
  CONTENT=$(echo "$HOOK_INPUT" | jq -r '.tool_input.new_string // .tool_input.content // empty' 2>/dev/null || echo "")
else
  CONTENT=$(echo "$HOOK_INPUT" | grep -oE '"new_string":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"new_string":\s*"//' | sed 's/"$//' || echo "")
  [[ -z "$CONTENT" ]] && CONTENT=$(echo "$HOOK_INPUT" | grep -oE '"content":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"content":\s*"//' | sed 's/"$//' || echo "")
fi

[[ -z "$CONTENT" ]] && exit 0

# Explicit provenance markers — the only thing that exempts a flagged line.
# Word/colon-anchored so substrings ("transform", "platform", "report") never match.
# source: rules/coding-standards.md §8 (Zetetic Source Discipline) — accepted provenance forms.
PROVENANCE='(source:|#[[:space:]]*ref:|//[[:space:]]*ref:|\bref:|\bdoi:|10\.[0-9]{4,}/|arxiv|\bpaper:|\bsee:|\bcitation:|https?://)'

# --- F3 fix: single-pass detection -------------------------------------------
# Previously this looped line-by-line, spawning up to 6 `grep` subprocesses per
# line (3 patterns x trigger+provenance recheck). That was an O(N) process-spawn
# storm: measured 38s for 50 lines, 70s+ for 200 — a soft-DoS on routine edits
# despite the advisory (exit 0) contract.
#
# Replacement: ONE `grep -nE` per pattern over the whole content (3 passes total,
# independent of line count). `-n` carries the line number; piping into
# `grep -viE "$PROVENANCE"` drops lines that carry a provenance marker. The grep
# regex engine is unchanged, so the EXACT A9 detection semantics are preserved:
#   * F1 case-sensitive UPPER_SNAKE-const assignment;
#   * F2/F3 word-anchored tuning tokens (case-insensitive);
#   * F4 comment-scoped algorithm claims (case-insensitive);
#   * provenance exemption identical (source:/ref:/doi:/arxiv/paper:/http...).
# The `<digits>:` prefix grep -n prepends cannot match any PROVENANCE alternative,
# so the provenance filter operates only on the real line content.

# F1: Magic number — NARROWED to "named-constant assigned a bare numeric literal".
# Only flags an UPPER_SNAKE_CASE identifier (the canonical constant smell) assigned a
# number, e.g. `MAX_RETRIES = 5`, `const TIMEOUT_MS: u64 = 3000`. Plain numeric lines
# (indices, loop bounds, version strings, struct fields) are NOT flagged — that 2+-digit
# heuristic produced false positives on ~69% of numeric lines (audit F1).
# Commit-time MAGIC_NUMBER coverage (floats ≥3 decimals, profile-gated) lives in
# tools/zetetic-checker.sh; this edit-time check is the advisory named-constant subset.
F1_HITS=$(printf '%s\n' "$CONTENT" \
  | grep -nE '\b[A-Z][A-Z0-9]*(_[A-Z0-9]+)+\b[^=]*[=:][^=]*[0-9]' 2>/dev/null \
  | grep -viE "$PROVENANCE" 2>/dev/null || true)

# F2/F3: Tuning constant assigned a number without explicit provenance.
# Exemption requires a real provenance marker (source:/ref:/doi:/arxiv/paper:), not the
# bare 'from' substring that previously matched "transform"/"platform" (audit F3).
F2_HITS=$(printf '%s\n' "$CONTENT" \
  | grep -niE '\b(threshold|alpha|beta|gamma|epsilon|lambda|weight|factor|coefficient|decay)\b[^=]*[=:][^=]*[0-9]' 2>/dev/null \
  | grep -viE "$PROVENANCE" 2>/dev/null || true)

# F4: Algorithm-citation claim — COMMENT-SCOPED. Only fires inside a comment
# (#, //, /*, *, or a docstring quote) so identifiers like `algorithm_id` in code
# are not flagged. Weak triggers 'following'/'based on' dropped (audit F4); the
# remaining tokens are explicit "this implements published work" claims.
F4_HITS=$(printf '%s\n' "$CONTENT" \
  | grep -niE '^[[:space:]]*(#|//|/\*|\*|"|'"'"').*\b(algorithm|implementation of|adapted from|derived from|ported from)\b' 2>/dev/null \
  | grep -viE "$PROVENANCE" 2>/dev/null || true)

# Emit one WARNING per hit, preserving the original per-line message text and the
# $FILE:$line_num location. The leading "<n>:" from grep -n is the line number.
if [[ -n "$F1_HITS" ]]; then
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    line_num=${hit%%:*}
    echo "WARNING: Named constant without provenance at $FILE:$line_num — add '# source: <ref>'"
    VIOLATIONS=$((VIOLATIONS + 1))
  done <<< "$F1_HITS"
fi

if [[ -n "$F2_HITS" ]]; then
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    line_num=${hit%%:*}
    echo "WARNING: Tuning constant without citation at $FILE:$line_num — zetetic standard requires source"
    VIOLATIONS=$((VIOLATIONS + 1))
  done <<< "$F2_HITS"
fi

if [[ -n "$F4_HITS" ]]; then
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    line_num=${hit%%:*}
    echo "WARNING: Algorithm reference without citation at $FILE:$line_num"
    VIOLATIONS=$((VIOLATIONS + 1))
  done <<< "$F4_HITS"
fi

if [[ $VIOLATIONS -gt 0 ]]; then
  echo ""
  echo "Claim gate: $VIOLATIONS potential zetetic violation(s). Consider adding source annotations."
fi

exit 0
