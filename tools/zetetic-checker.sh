#!/usr/bin/env bash
# zetetic-checker.sh — Scan code for zetetic standard violations
#
# Usage:
#   tools/zetetic-checker.sh --staged              # check only lines added in staged diff (commit gate)
#   tools/zetetic-checker.sh --files <f1> <f2> ... # check specific files (review / CI)
#   tools/zetetic-checker.sh --full                # recursively scan tracked files (audit sweep)
#
# Checks:
#   - UNSOURCED (error): an absolute word ("always"/"never") or self-evidence appeal
#       paired with an evaluative word (works/correct/best/...), or a bare rhetorical
#       appeal (an "everyone-knows" style assertion), uncited. Behavioral comments excluded.
#   - MAGIC_NUMBER (warning): floats with ≥3 decimals without a `# source:` / `// source:` annotation
#   - TODO_NO_REF (warning): TODO/FIXME/HACK without a difficulty-book or issue reference
#
# Severity model:
#   - UNSOURCED is always blocking. Claim-pairing keeps the false-positive rate near zero (see check_line).
#   - MAGIC_NUMBER / TODO_NO_REF are warnings by default. They block only when ZETETIC_PROFILE=strict.
#   - ZETETIC_PROFILE must be declared in .zetetic.conf (committed, auditable) — no silent env override.
#
# Exit codes: 0 clean, 1 violations found (errors in default; errors OR warnings in strict), 2 usage error.
#
# Rule provenance: enforces rules/coding-standards.md §8 (Zetetic Source Discipline).

set -euo pipefail

# ── Defaults ───────────────────────────────────────────────────────────
# Always skip: generated / lock / binary-ish files. The zetetic standard targets authored code.
ZETETIC_SKIP_PATHS_ALWAYS='Cargo\.lock$|package-lock\.json$|yarn\.lock$|pnpm-lock\.yaml$|poetry\.lock$|Gemfile\.lock$|composer\.lock$|target/|node_modules/|dist/|build/|\.git/|\.venv/|vendor/|\.sqlx/'
ZETETIC_SKIP_EXT_ALWAYS='\.(lock|svg|png|jpg|jpeg|gif|webp|pdf|min\.js|min\.css)$'

# Default-skip-but-configurable: data / config formats. Teams may re-enable via .zetetic.conf.
ZETETIC_SKIP_EXT_DEFAULT='\.(json|yaml|yml|toml|csv|sql|tsv|xml)$'

# Always process .md excluded (per original behavior — docs aren't algorithms).
ZETETIC_SKIP_EXT_DOCS='\.md$'

# Profile — must be declared in .zetetic.conf. No default; absence means "standard".
ZETETIC_PROFILE="${ZETETIC_PROFILE:-standard}"

# ── Project-local config ──────────────────────────────────────────────
# Only files/paths may be overridden by project config. Rule semantics (which checks exist) cannot be disabled.
load_project_config() {
  local repo_root; repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  for cfg in "$repo_root/.zetetic.conf" "$repo_root/.claude/zetetic.conf"; do
    if [[ -f "$cfg" ]]; then
      # Source in subshell first to detect forbidden rule overrides
      local forbidden
      forbidden=$(grep -E '^[[:space:]]*(DISABLE_UNSOURCED|DISABLE_MAGIC_NUMBER|DISABLE_TODO_NO_REF|SKIP_RULE|EXCLUDE_RULE)=' "$cfg" 2>/dev/null || true)
      if [[ -n "$forbidden" ]]; then
        echo "ERROR: $cfg contains forbidden rule-exclusion directive:" >&2
        echo "$forbidden" >&2
        echo "The zetetic-checker config may override file/path exclusions and ZETETIC_PROFILE only." >&2
        echo "Rules themselves (UNSOURCED, MAGIC_NUMBER, TODO_NO_REF) cannot be disabled." >&2
        exit 2
      fi
      # shellcheck disable=SC1090
      source "$cfg"
      return
    fi
  done
}
load_project_config

# Validate profile value
case "$ZETETIC_PROFILE" in
  strict|standard|permissive) ;;
  *) echo "ERROR: ZETETIC_PROFILE must be strict|standard|permissive (got: $ZETETIC_PROFILE)" >&2; exit 2 ;;
esac

# ── Argument parsing ───────────────────────────────────────────────────
MODE=""
FILES=()
if [[ "${1:-}" == "--staged" ]]; then
  MODE="staged"
elif [[ "${1:-}" == "--files" ]]; then
  MODE="files"; shift
  FILES=("$@")
elif [[ "${1:-}" == "--full" ]]; then
  MODE="full"
else
  sed -n '2,/^$/s/^# \?//p' "$0"
  exit 2
fi

# ── Should-skip decision ──────────────────────────────────────────────
should_skip_file() {
  local f="$1"
  # Always-skip paths
  [[ "$f" =~ $ZETETIC_SKIP_PATHS_ALWAYS ]] && return 0
  # Always-skip extensions (binaries, auto-generated)
  [[ "$f" =~ $ZETETIC_SKIP_EXT_ALWAYS ]] && return 0
  # Docs
  [[ "$f" =~ $ZETETIC_SKIP_EXT_DOCS ]] && return 0
  # Default-skip data/config — unless project re-enabled via .zetetic.conf
  if [[ "${ZETETIC_CHECK_DATA_FORMATS:-false}" != "true" ]]; then
    [[ "$f" =~ $ZETETIC_SKIP_EXT_DEFAULT ]] && return 0
  fi
  # Binary detection via --mime-encoding, NOT --mime-type: libmagic TYPE
  # names for source text vary by version (file-5.45 on ubuntu-24.04 types
  # IIFE-opening JS as application/javascript; file-5.41 on macOS says
  # text/plain), so a `^text/` type filter silently skipped real source on
  # Linux CI. Encoding is version-stable: non-text reports exactly `binary`.
  # Missing/failing `file` means "do not skip" — never silently disarm the gate.
  # source: measured 2026-07-14, file-5.41 vs file-5.45,
  # zetetic-team-subagents PR #17 CI run 29297173451 (same fix as
  # craftsmanship-checker.sh should_skip_file).
  if [[ -f "$f" ]]; then
    [[ "$(file -b --mime-encoding "$f" 2>/dev/null)" == "binary" ]] && return 0
  fi
  return 1
}

# ── Collect files + lines ──────────────────────────────────────────────
# Produces tab-separated output: "<path>\t<line_num>\t<line_content>"
collect_lines_staged() {
  # Use -U0 to get only added lines with line numbers (preserves authorial responsibility)
  # Handle renamed files: --diff-filter includes R, and we re-scan the whole file's added side
  local file line_num
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    should_skip_file "$file" && continue
    # For each added line in the diff, extract the new line number
    # `git diff -U0` output: `@@ -a,b +c,d @@` then `+content`
    git diff --cached -U0 --diff-filter=ACMR -- "$file" 2>/dev/null | awk -v file="$file" '
      /^@@/ {
        # Parse +c,d — new starting line
        match($0, /\+[0-9]+/); new_line = substr($0, RSTART+1, RLENGTH-1) + 0
        next
      }
      /^\+/ && !/^\+\+\+/ {
        # Emit: file, new_line, line content (strip leading +)
        printf "%s\t%d\t%s\n", file, new_line, substr($0, 2)
        new_line++
      }
    '
  done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
}

collect_lines_files() {
  local file line_num
  for file in "${FILES[@]}"; do
    [[ ! -f "$file" ]] && continue
    should_skip_file "$file" && continue
    line_num=0
    while IFS= read -r line; do
      line_num=$((line_num + 1))
      printf '%s\t%d\t%s\n' "$file" "$line_num" "$line"
    done < "$file"
  done
}

collect_lines_full() {
  local repo_root; repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  local file line_num
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    should_skip_file "$file" && continue
    line_num=0
    while IFS= read -r line; do
      line_num=$((line_num + 1))
      printf '%s\t%d\t%s\n' "$file" "$line_num" "$line"
    done < "$repo_root/$file"
  done < <(cd "$repo_root" && git ls-files 2>/dev/null)
}

# ── Checks ─────────────────────────────────────────────────────────────
ERRORS=0
WARNINGS=0

# UNSOURCED — unsourced claims of correctness or universality. Always an error.
#
# Fires only inside comments / string literals. Two shapes are flagged:
#   1. an absolute quantifier or self-evidence adverb, paired (same comment,
#      within ~40 chars) with an evaluative word from the claim group below;
#   2. a bare rhetorical appeal from the self-evidence group below.
# The pairing is what turns it into a *claim about the world* rather than a
# *description of code*. Behavioral comments are deliberately NOT flagged,
# because the absolute word stands alone with no claim word nearby:
#   "this hook never blocks", "permissive always exits 0", instruction prose.
# source: measured on 2026-06-23 against a full-repo --full scan — the prior
#   bare-absolute-word trigger produced 64 findings, all 64 false positives
#   (behavioral comments); claim-pairing drops that to 0 while the
#   true-positive fixture still fires. Regression fixtures live in
#   tools/tests/zetetic-checker/fixture-behavioral-negative.py and
#   fixture-selfevident-claim.py.
# Known limitation (precision over recall — a commit gate must not cry wolf):
#   claims phrased with ambiguous words are NOT caught, e.g. "always faster",
#   "clearly the best", "never deadlocks", "clearly O(1)". A noisy gate gets
#   bypassed; review/PR is the backstop for those. Widen only with new fixtures.
check_unsourced() {
  local file="$1" line_num="$2" line="$3"
  local _u_mark='(#|//|/\*|\*|"|'"'"')'
  local _u_assert='(always|never|obviously|clearly)'
  # Claim group = words that are unambiguously quality judgments. Direction /
  # category / superlative words (right, safe, best, optimal, fastest, secure,
  # guaranteed, identical, ...) are EXCLUDED: in code they name nouns
  # ("right child", "fast path", "safe list", "guaranteed delivery"), not claims.
  # source: adversarial review 2026-06-23 — 22 benign idioms across py/sh/rs/ts
  #   fired on those words; restricting to judgment words drops that to 0.
  local _u_claim='(works?|correct|incorrect|wrong|buggy|broken|flawless|foolproof|bulletproof|infallible)'
  local _u_evident='(everyone knows|everybody knows|goes without saying|needless to say|well[ -]known fact|trivially (true|correct|obvious))'   # see: provenance comment above
  # Forward only (assert THEN claim, within ~24 chars). The reverse order is
  # almost a hedged conditional ("correct only when ... is held") and is not matched.
  local _u_pattern="${_u_mark}.*(\\b${_u_assert}\\b.{0,24}\\b${_u_claim}\\b|\\b${_u_evident}\\b)"
  if echo "$line" | grep -qiE "$_u_pattern" 2>/dev/null; then
    if ! echo "$line" | grep -qiE 'source:|ref:|see:|citation:|cite:' 2>/dev/null; then
      echo "UNSOURCED   (error)    $file:$line_num: $(echo "$line" | head -c 80)"
      ERRORS=$((ERRORS + 1))
    fi
  fi
}

# MAGIC_NUMBER — floats with 3+ decimals (the canonical unsourced-literal smell).
# Integer tuning params (batch_size=128, epochs=50) are NOT flagged — use review + naming conventions.
check_magic_number() {
  local file="$1" line_num="$2" line="$3"
  if echo "$line" | grep -qE '[^a-zA-Z_0-9."]([0-9]+\.[0-9]{3,})' 2>/dev/null; then
    if ! echo "$line" | grep -qiE 'source:|ref:|#.*from|//.*from|version|test|assert|approx|expect|tolerance|epsilon|pi|tau|e_|ln|log' 2>/dev/null; then
      local severity="warn"
      [[ "$ZETETIC_PROFILE" == "strict" ]] && severity="error"
      echo "MAGIC_NUMBER ($severity)    $file:$line_num: $(echo "$line" | head -c 80)"
      if [[ "$severity" == "error" ]]; then
        ERRORS=$((ERRORS + 1))
      else
        WARNINGS=$((WARNINGS + 1))
      fi
    fi
  fi
}

# TODO_NO_REF — TODO/FIXME/HACK without difficulty-book or issue reference.
check_todo_no_ref() {
  local file="$1" line_num="$2" line="$3"
  if echo "$line" | grep -qiE '\b(TODO|FIXME|HACK|XXX)\b' 2>/dev/null; then
    if ! echo "$line" | grep -qiE 'difficulty.book|DB#|db-entry|tracked|issue|#[0-9]|[A-Z]+-[0-9]+' 2>/dev/null; then
      local severity="warn"
      [[ "$ZETETIC_PROFILE" == "strict" ]] && severity="error"
      echo "TODO_NO_REF  ($severity)    $file:$line_num: $(echo "$line" | head -c 80)"
      if [[ "$severity" == "error" ]]; then
        ERRORS=$((ERRORS + 1))
      else
        WARNINGS=$((WARNINGS + 1))
      fi
    fi
  fi
}

# One line through every rule. Runs in the main shell so the rule functions'
# ERRORS/WARNINGS increments are visible to the final summary.
check_line() {
  local file="$1" line_num="$2" line="$3"
  check_unsourced "$file" "$line_num" "$line"
  check_magic_number "$file" "$line_num" "$line"
  check_todo_no_ref "$file" "$line_num" "$line"
}

# ── Project-local extension (optional) ────────────────────────────────
# If present, sourced before running checks. Extension scripts can add checks that increment
# ERRORS/WARNINGS. They cannot disable built-in checks (see load_project_config guard).
load_project_extension() {
  local repo_root; repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  for ext in "$repo_root/.zetetic-check.sh" "$repo_root/.claude/zetetic-check.sh"; do
    if [[ -f "$ext" ]]; then
      # shellcheck disable=SC1090
      source "$ext"
      return
    fi
  done
}
load_project_extension

# ── Main loop ──────────────────────────────────────────────────────────
case "$MODE" in
  staged) COLLECT=collect_lines_staged ;;
  files)  COLLECT=collect_lines_files ;;
  full)   COLLECT=collect_lines_full ;;
esac

while IFS=$'\t' read -r file line_num line; do
  [[ -z "$file" ]] && continue
  check_line "$file" "$line_num" "$line"
done < <($COLLECT)

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "Profile: $ZETETIC_PROFILE  ($MODE mode)"
echo "Errors:   $ERRORS  (blocking)"
echo "Warnings: $WARNINGS  (informational — promoted to errors when profile=strict)"

if [[ "$ZETETIC_PROFILE" == "permissive" ]]; then
  # Permissive never blocks, but still reports.
  echo "PASSED (permissive): all findings are informational."
  exit 0
fi

if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: $ERRORS blocking violation(s)."
  [[ "$ZETETIC_PROFILE" == "strict" ]] && echo "       (MAGIC_NUMBER and TODO_NO_REF promoted to errors under strict profile.)"
  exit 1
fi

echo "PASSED: no blocking violations."
exit 0
