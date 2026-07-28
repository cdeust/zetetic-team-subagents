#!/usr/bin/env bash
# craftsmanship-checker.sh — Scan code for coding-standards §4 (size) + select
# craftsmanship violations. Sibling of zetetic-checker.sh; same harness, same
# exit contract, same config mechanism.
#
# Usage:
#   tools/craftsmanship-checker.sh --staged              # commit gate (whole changed FILES)
#   tools/craftsmanship-checker.sh --files <f1> <f2> ... # review / CI on named files
#   tools/craftsmanship-checker.sh --full                # audit sweep over tracked files
#
# Exit codes: 0 no blocking findings (or permissive), 1 blocking findings, 2 usage/config error.
# (pre-commit treats any non-zero as a block, so usage errors also stop a commit — intended.)
#
# Profile (CRAFTSMANSHIP_PROFILE): strict | standard | permissive (default standard).
#   standard   — errors block, warnings inform.
#   strict     — warnings promoted to errors.
#   permissive — always exit 0, still reports.
# A committed .craftsmanship.conf value OVERRIDES the live env (sourced after the env default).
# Bad profile value => exit 2 to stderr.
#
# Config is FULLY TUNABLE INCLUDING OFF (user decision): a team may relax a
# threshold, downgrade a rule block->advise, or turn it off. Unlike zetetic-checker,
# there is NO anti-tamper guard. Defaults stay strict and sourced (see below).
#
# Findings + summary go to STDOUT. stderr is reserved for usage/config errors.
# Per finding: '<RULE> (<error|warn>)    <file>:<line>: <head -c 80 of line>'.
#
# Detectors (audit §5). BLOCK = deterministic; ADVISE = heuristic.
#   1 FILE_TOO_LONG        §4.1 BLOCK (language-agnostic, wc -l)
#   2 NESTING_TOO_DEEP     §4.5 BLOCK (brace depth / python indent; bash+unknown fail-open)
#   3 FUNCTION_TOO_LONG    §4.2 BLOCK recognized langs, fail-open otherwise
#   4 CLASS_TOO_LONG       §4.3 BLOCK recognized langs, fail-open otherwise
#   5 PARAM_COUNT          §4.4 BLOCK recognized langs, fail-open otherwise
#   6 LAYER_VIOLATION      §2.2 ADVISE by default (configurable); fail-open off-layer
#   7 GRABBAG_NAME         §9   ADVISE (common/shared excluded — sanctioned layers)
#   8 LSP_NOTIMPL          §1.3 ADVISE (cannot prove an override)
#   9 CORE_CONCRETE_INSTANTIATION §5.2 ADVISE, default OFF (high FP risk)
#
# NON-GOALS (judgment / whole-program rules — deliberately NOT faked; faking
# judgment trains agents to ignore the checker, §7.3):
#   §1.1 SRP, §1.4 ISP, §3.3 rule-of-three, §5.3 service-locator, §5.4 typed-injection,
#   §9 dead-code (delegate to vulture / ts-prune / cargo-machete), §6 root-cause,
#   and mutation / test-strength (owned by test-engineer Move 8).
#
# .md policy: structural rules target CODE files; recognized-grammar gating means
# .md never matches a recognized language, so FUNCTION/CLASS/PARAM fail-open on .md
# and only FILE_TOO_LONG / NESTING (brace) could fire. We deliberately SKIP .md by
# default (docs are not subject to §4 size limits); a repo with structured .md
# source can re-enable via CRAFTSMANSHIP_CHECK_DOCS=true in .craftsmanship.conf.
#
# Rule provenance: rules/coding-standards.md §4, §2.2, §9, §1.3, §5.2.

set -euo pipefail

# ── Defaults (thresholds) ──────────────────────────────────────────────
# source: rules/coding-standards.md §4 (Martin 2008, Clean Code Ch.3 & Ch.10).
# A committed .craftsmanship.conf overrides any of these (fully tunable).
FILE_MAX="${FILE_MAX:-500}"    # §4.1
# §4.1 test-file exception (test-engineer agent domain-context): test files may
# exceed §4.1 when organized by fixture grouping (sharding would duplicate shared
# fixtures across files, raising coupling). Applied ONLY to files matching
# TEST_FILE_RE — production source stays bound by FILE_MAX. Advisory ceiling kept
# to still catch a runaway test file; no published numeric source, so tunable.
TEST_FILE_MAX="${TEST_FILE_MAX:-2000}"
TEST_FILE_RE="${TEST_FILE_RE:-(^|/)(tests?/|test_|conftest\.py$)|_test\.[a-z]+$|\.spec\.[a-z]+$|\.test\.[a-z]+$}"
FUNC_MAX="${FUNC_MAX:-50}"     # §4.2
CLASS_MAX="${CLASS_MAX:-300}"  # §4.3
PARAM_MAX="${PARAM_MAX:-4}"    # §4.4
NEST_MAX="${NEST_MAX:-3}"      # §4.5

# Per-rule severity: block | advise | off.
# NESTING note (CRAFT-NEST-BRACE-FP): §4.5 governs nested CONTROL FLOW. For
# brace languages we cannot reliably separate control braces from DATA/object
# braces in shell, so a brace-depth count over-reports on object/array literals
# (e.g. a JSON-schema literal reads as "depth 5"). To honor the project's
# never-cry-wolf contract, brace-language nesting defaults to ADVISE and never
# blocks by default — see SEV_NESTING_BRACE below. Python INDENT-based nesting
# is sound (only control headers count), so it keeps the BLOCK default here.
# Whether the operator explicitly chose a nesting severity is captured BEFORE
# the default is applied, so an explicit choice still drives the brace variant.
CRAFT_NESTING_SEV_WAS_SET="${SEV_NESTING_TOO_DEEP+set}"
SEV_FILE_TOO_LONG="${SEV_FILE_TOO_LONG:-block}"
SEV_NESTING_TOO_DEEP="${SEV_NESTING_TOO_DEEP:-block}"
SEV_FUNCTION_TOO_LONG="${SEV_FUNCTION_TOO_LONG:-block}"
SEV_CLASS_TOO_LONG="${SEV_CLASS_TOO_LONG:-block}"
SEV_PARAM_COUNT="${SEV_PARAM_COUNT:-block}"
SEV_LAYER_VIOLATION="${SEV_LAYER_VIOLATION:-advise}"
SEV_GRABBAG_NAME="${SEV_GRABBAG_NAME:-advise}"
SEV_LSP_NOTIMPL="${SEV_LSP_NOTIMPL:-advise}"
SEV_CORE_INSTANTIATION="${SEV_CORE_INSTANTIATION:-off}"

# Stakes-flex (§10): sizes get a 1.2x advisory band. >limit and <=band*limit =>
# advise; >band*limit => the rule's configured severity.
SIZE_FLEX_BAND="${SIZE_FLEX_BAND:-1.2}"

# Profile default (env). Config may override.
CRAFTSMANSHIP_PROFILE="${CRAFTSMANSHIP_PROFILE:-standard}"

# Skip-lists (mirror zetetic-checker). Generated / lock / binary-ish files.
CRAFT_SKIP_PATHS='Cargo\.lock$|package-lock\.json$|yarn\.lock$|pnpm-lock\.yaml$|poetry\.lock$|Gemfile\.lock$|composer\.lock$|target/|node_modules/|dist/|build/|\.git/|\.venv/|vendor/|\.sqlx/'
CRAFT_SKIP_EXT='\.(lock|svg|png|jpg|jpeg|gif|webp|pdf|min\.js|min\.css)$'
CRAFT_SKIP_EXT_DATA='\.(json|yaml|yml|toml|csv|sql|tsv|xml)$'
CRAFT_SKIP_EXT_DOCS='\.md$'

# ── Project-local config ───────────────────────────────────────────────
# Sourced AFTER the env defaults so a committed value overrides the live env.
# Fully tunable including OFF — no anti-tamper guard (user decision).
craft_repo_root() { git rev-parse --show-toplevel 2>/dev/null || pwd; }

load_project_config() {
  local root cfg
  root="$(craft_repo_root)"
  for cfg in "$root/.craftsmanship.conf" "$root/.claude/craftsmanship.conf"; do
    if [[ -f "$cfg" ]]; then
      # shellcheck disable=SC1090
      source "$cfg"
      return 0
    fi
  done
}
# Snapshot the nesting severity as the env-defaults left it (default 'block'),
# so a config file that sets SEV_NESTING_TOO_DEEP can be detected as an explicit
# operator choice that should also drive the brace variant.
CRAFT_NESTING_SEV_PRECONFIG="$SEV_NESTING_TOO_DEEP"
load_project_config

# Brace-language nesting severity (CRAFT-NEST-BRACE-FP). Resolve precedence:
#   1. an explicit SEV_NESTING_BRACE (env or config) wins;
#   2. else, if the operator explicitly chose SEV_NESTING_TOO_DEEP (set in the
#      env before defaults, or changed by config), brace nesting inherits it;
#   3. else default ADVISE so brace nesting never false-BLOCKS valid code.
craft_resolve_nesting_brace_sev() {
  if [[ -n "${SEV_NESTING_BRACE:-}" ]]; then
    return 0
  fi
  if [[ -n "$CRAFT_NESTING_SEV_WAS_SET" ]] \
     || [[ "$SEV_NESTING_TOO_DEEP" != "$CRAFT_NESTING_SEV_PRECONFIG" ]]; then
    SEV_NESTING_BRACE="$SEV_NESTING_TOO_DEEP"
  else
    SEV_NESTING_BRACE="advise"
  fi
}
craft_resolve_nesting_brace_sev

# Validate profile (after config, since config may set it).
case "$CRAFTSMANSHIP_PROFILE" in
  strict|standard|permissive) ;;
  *) echo "ERROR: CRAFTSMANSHIP_PROFILE must be strict|standard|permissive (got: $CRAFTSMANSHIP_PROFILE)" >&2; exit 2 ;;
esac

# ── Source detector library ────────────────────────────────────────────
CRAFT_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRAFT_LIB="$CRAFT_SELF_DIR/lib/craftsmanship-detectors.sh"
if [[ ! -f "$CRAFT_LIB" ]]; then
  echo "ERROR: detector library not found at $CRAFT_LIB" >&2
  exit 2
fi
# shellcheck disable=SC1090
source "$CRAFT_LIB"

# ── Argument parsing (first-positional dispatch) ───────────────────────
MODE=""
FILES=()
case "${1:-}" in
  --staged) MODE="staged" ;;
  --files)  MODE="files"; shift; FILES=("$@") ;;
  --full)   MODE="full" ;;
  # POSIX bracket class instead of GNU '\?': BSD/macOS sed treats '\?' literally,
  # which silently prints an empty help. '[[:space:]]*' works on both seds.
  *) sed -n '2,/^$/s/^#[[:space:]]*//p' "$0"; exit 2 ;;
esac

# ── Should-skip decision ───────────────────────────────────────────────
should_skip_file() {
  local f="$1"
  [[ "$f" =~ $CRAFT_SKIP_PATHS ]] && return 0
  [[ "$f" =~ $CRAFT_SKIP_EXT ]] && return 0
  if [[ "${CRAFTSMANSHIP_CHECK_DOCS:-false}" != "true" ]]; then
    [[ "$f" =~ $CRAFT_SKIP_EXT_DOCS ]] && return 0
  fi
  if [[ "${CRAFTSMANSHIP_CHECK_DATA:-false}" != "true" ]]; then
    [[ "$f" =~ $CRAFT_SKIP_EXT_DATA ]] && return 0
  fi
  # Binary detection via --mime-encoding, NOT --mime-type: libmagic names
  # source text inconsistently across versions — file-5.45 (ubuntu-24.04)
  # types a `(function () {`-opening JS module as application/javascript
  # while file-5.41 (macOS) says text/plain — so a `^text/` TYPE filter
  # silently skipped real source files on Linux CI (0 findings, exit 0).
  # ENCODING answers the actual question ("is this binary?") and is
  # version-stable: non-text content reports exactly `binary`. A missing or
  # failing `file` binary now means "do not skip" — a hard gate that
  # silently skips every file is worse than occasionally scanning a binary.
  # source: measured 2026-07-14, file-5.41 (macOS) vs file-5.45
  # (ubuntu:24.04), zetetic-team-subagents PR #17 CI run 29297173451.
  if [[ -f "$f" ]]; then
    [[ "$(file -b --mime-encoding "$f" 2>/dev/null)" == "binary" ]] && return 0
  fi
  return 1
}

# ── File discovery ─────────────────────────────────────────────────────
# CRITICAL (audit C1-5): structural rules need WHOLE-FILE context. For --staged
# we derive the changed-FILE set and re-read each in full — scoring from staged
# added-lines in isolation would silently disable detectors 1-5 in the commit gate.
collect_files_staged() {
  local file root; root="$(craft_repo_root)"
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    should_skip_file "$file" && continue
    [[ -f "$root/$file" ]] && echo "$root/$file"
  done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
}

collect_files_named() {
  local file
  for file in "${FILES[@]}"; do
    [[ ! -f "$file" ]] && continue
    should_skip_file "$file" && continue
    echo "$file"
  done
}

collect_files_full() {
  local file root; root="$(craft_repo_root)"
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    should_skip_file "$file" && continue
    [[ -f "$root/$file" ]] && echo "$root/$file"
  done < <(cd "$root" 2>/dev/null && git ls-files 2>/dev/null)
}

# ── Finding accounting ─────────────────────────────────────────────────
ERRORS=0
WARNINGS=0

# Resolve a rule's effective severity by indirection on its SEV_* variable,
# applying the strict-profile promotion (advise -> block). Echoes block|advise|off.
craft_effective_sev() {
  local sevvar="$1" sev="${!1:-advise}"
  if [[ "$sev" == "advise" ]] && [[ "$CRAFTSMANSHIP_PROFILE" == "strict" ]]; then
    sev="block"
  fi
  echo "$sev"
}

# Emit one finding RECORD. Args: RULE SEVVAR FILE LINE RAWLINE MESSAGE.
# Detectors run inside pipelines (subshells), so emit MUST NOT mutate the
# ERRORS/WARNINGS counters here — the increments would be lost with the subshell.
# Instead it writes a tab-delimited record to stdout; the main-shell consumer
# (craft_consume) resolves severity, formats, and counts. Newlines/tabs in the
# snippet are stripped so each finding is exactly one record line.
craft_emit() {
  local rule="$1" sevvar="$2" f="$3" ln="$4" raw="$5" msg="$6"
  local snippet
  snippet=$(printf '%s' "$raw" | head -c 80 | tr '\t\n' '  ')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$rule" "$sevvar" "$f" "$ln" "$snippet" "$msg"
}

# Size-rule helper applying the §10 flex band. Args:
#   RULE SEVVAR FILE LINE VALUE LIMIT BAND MESSAGE [RAWLINE]
# >limit and <=band*limit => advise; >band*limit => the rule's configured severity.
craft_size_finding() {
  local rule="$1" sevvar="$2" f="$3" ln="$4" val="$5" limit="$6" band="$7"
  local msg="$8" raw="${9:-}"
  [[ "$val" -le "$limit" ]] && return 0
  local threshold
  threshold=$(awk -v l="$limit" -v b="$band" 'BEGIN{ printf "%d", l*b }')
  [[ -z "$raw" ]] && raw="$msg"
  if [[ "$val" -le "$threshold" ]]; then
    craft_emit "$rule" "SEV___ADVISE_BAND__" "$f" "$ln" "$raw" "$msg (within ${band}x flex band — advisory)"
  else
    craft_emit "$rule" "$sevvar" "$f" "$ln" "$raw" "$msg"
  fi
}

# Synthetic SEV var for the flex band: always advise (unless strict promotes it).
# craft_size_finding passes this NAME to craft_emit, and craft_effective_sev
# resolves it by indirection, exactly like every real rule's SEV_* variable.
# Assigned unconditionally (not `${SEV___ADVISE_BAND__:-advise}`) because the
# flex band is not an operator-tunable rule: it is the §10 tolerance around a
# rule that already has its own severity knob.
#
# Reported unused (SC2034) because its only reader is the indirect expansion
# ${!1} in craft_effective_sev, reached via a string-literal argument. Every
# other SEV_* escapes the same report only by self-referencing inside its own
# `${SEV_X:-block}` default.
# shellcheck disable=SC2034
SEV___ADVISE_BAND__="advise"

# ── Per-file driver ────────────────────────────────────────────────────
check_file() {
  local f="$1" lang file_max="$FILE_MAX"
  lang="$(craft_lang_of "$f")"
  [[ "$f" =~ $TEST_FILE_RE ]] && file_max="$TEST_FILE_MAX"
  craft_d1_file_too_long      "$f" "$file_max"  "$SIZE_FLEX_BAND"
  craft_d2_nesting_too_deep   "$f" "$NEST_MAX"  "$lang"
  craft_d3_function_too_long  "$f" "$FUNC_MAX"  "$SIZE_FLEX_BAND" "$lang"
  craft_d4_class_too_long     "$f" "$CLASS_MAX" "$SIZE_FLEX_BAND" "$lang"
  craft_d5_param_count        "$f" "$PARAM_MAX" "$lang"
  craft_d6_layer_violation    "$f"
  craft_d7_grabbag_name       "$f"
  craft_d8_lsp_notimpl        "$f"
  craft_d9_core_instantiation "$f"
  return 0  # detectors may return non-zero on a no-match tail; never abort the loop
}

# Produce all finding RECORDS (one per line) for the selected file set. Runs the
# detectors; their craft_emit output is the record stream. Stays in this pipeline.
emit_all_records() {
  local target
  while IFS= read -r target; do
    [[ -z "$target" ]] && continue
    check_file "$target"
  done < <($COLLECT)
}

# Main-shell consumer: read each record, resolve severity (honors off / strict
# promotion), format the human line, and count. Counting happens HERE in the main
# shell (records arrive via process substitution feeding this while loop, whose
# body runs in the main shell — same pattern as zetetic-checker's check_line loop).
craft_consume() {
  local rule sevvar f ln snippet msg sev label
  while IFS=$'\t' read -r rule sevvar f ln snippet msg; do
    [[ -z "$rule" ]] && continue
    sev="$(craft_effective_sev "$sevvar")"
    [[ "$sev" == "off" ]] && continue
    if [[ "$sev" == "block" ]]; then
      label="error"; ERRORS=$((ERRORS + 1))
    else
      label="warn"; WARNINGS=$((WARNINGS + 1))
    fi
    printf '%-28s (%s)    %s:%s: %s\n' "$rule" "$label" "$f" "$ln" "$snippet"
    [[ -n "$msg" ]] && printf '    -> %s\n' "$msg"
  done
}

# ── Main ───────────────────────────────────────────────────────────────
case "$MODE" in
  staged) COLLECT=collect_files_staged ;;
  files)  COLLECT=collect_files_named ;;
  full)   COLLECT=collect_files_full ;;
esac

craft_consume < <(emit_all_records)

# ── Summary ────────────────────────────────────────────────────────────
echo ""
echo "Profile: $CRAFTSMANSHIP_PROFILE  ($MODE mode)"
echo "Errors:   $ERRORS  (blocking)"
echo "Warnings: $WARNINGS  (advisory — promoted to errors when profile=strict)"

if [[ "$CRAFTSMANSHIP_PROFILE" == "permissive" ]]; then
  echo "PASSED (permissive): all findings are informational."
  exit 0
fi

if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: $ERRORS blocking violation(s)."
  [[ "$CRAFTSMANSHIP_PROFILE" == "strict" ]] && echo "       (advisory rules promoted to errors under strict profile.)"
  exit 1
fi

echo "PASSED: no blocking violations."
exit 0
