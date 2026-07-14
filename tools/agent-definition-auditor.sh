#!/usr/bin/env bash
# agent-audit.sh — Verify every agent definition will not underperform.
#
# Checks per file (compatible with bash 3.2):
#   F1  frontmatter starts with --- on line 1
#   F2  has name field
#   F3  has description field
#   F4  has model field           (v2.9.0 schema)
#   F5  has effort field          (v2.9.0 schema)
#   F6  has when_to_use field
#   F7  has agent_topic field
#   F8  has tools field           (past lesson: empty tools = commit failures)
#   F9  tools list non-empty
#   FD  description value >= 40 chars, no orphan quote / broken escaping
#       (issue #19: deming/fisher/leguin/ranganathan shipped with descriptions
#       truncated to "\"W.", "Ronald A.", "Ursula K.", "S.R." — unroutable by
#       spawn/routing since description is the routing criterion)
#   B1  body has <identity> tag
#   B2  body has Move 1 anchor       (exempt for scribe-kind: body has <procedure> instead)
#   B3  body has at least 3 Moves    (exempt for scribe-kind: body has <procedure> instead)
#   G1  genius-only: shapes field
#   G2  genius-only: primary sources / citations
#   G3  genius-only: <revolution> section
#   P1  collaboration hint (Pair / Distinct from / Hand off)

set -uo pipefail

# ROOT defaults to <repo-root>/agents, resolved relative to this script's own
# location (not the caller's cwd) so the auditor works identically from any
# invocation directory and on any machine/CI runner — the previous default
# was a personal absolute path that silently matched 0 files in CI, letting
# the whole audit (F1-F9, B1-B3, G1-G3, P1) pass vacuously.
# source: issue #21 (agent-definition-auditor.sh never ran in CI)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${1:-$REPO_ROOT/agents}"
TEAM_DIR="$ROOT"
GEN_DIR="$ROOT/genius"

files=0; blockers=0; warnings=0

# Per-check pass/fail tallies (bash 3.2: parallel arrays)
CHECKS="F1 F2 F3 F4 F5 F6 F7 F8 F9 FD B1 B2 B3 G1 G2 G3 P1"
F1p=0; F1f=0; F2p=0; F2f=0; F3p=0; F3f=0; F4p=0; F4f=0
F5p=0; F5f=0; F6p=0; F6f=0; F7p=0; F7f=0; F8p=0; F8f=0
F9p=0; F9f=0; FDp=0; FDf=0; B1p=0; B1f=0; B2p=0; B2f=0; B3p=0; B3f=0
G1p=0; G1f=0; G2p=0; G2f=0; G3p=0; G3f=0; P1p=0; P1f=0

# Minimum description length (chars, inner value, excludes surrounding quotes).
# source: issue #19 — 40 chars is the shortest length that forces a trigger
# clause, an output noun, and a distinctive marker into one sentence (verified
# against the 79 currently-compliant genius descriptions, all >= 45 chars).
FD_MIN_LEN=40

BLOCKERS_FILE=$(mktemp)
WARNINGS_FILE=$(mktemp)

# fld_present file fieldname -> 0 if present, 1 if missing
fld_present() {
  grep -qE "^${2}:" "$1"
}

check_fm() {
  local f="$1" rel="$2" fld="$3" var_p="$4" var_f="$5" severity="$6"
  if fld_present "$f" "$fld"; then
    eval "$var_p=\$(( $var_p + 1 ))"
  else
    eval "$var_f=\$(( $var_f + 1 ))"
    if [[ "$severity" == "BLOCKER" ]]; then
      echo "BLOCKER $rel: missing frontmatter field '$fld'" >> "$BLOCKERS_FILE"
      blockers=$(( blockers + 1 ))
    else
      echo "WARNING $rel: missing frontmatter field '$fld'" >> "$WARNINGS_FILE"
      warnings=$(( warnings + 1 ))
    fi
  fi
}

# check_description_quality — FD: description >= FD_MIN_LEN chars, no broken
# JSON-escaping artifact (issue #19 regression guard). Split out of
# check_file() to keep that function under coding-standards.md §4.2 (50 lines).
# F3 (field presence) already ran; a truncated value like `description: "\"W."`
# passes F3 but is unroutable (routing runs on this string, same mechanism as
# Skills) — that gap is what FD closes.
check_description_quality() {
  local f="$1" rel="$2"
  local desc_line
  desc_line=$(grep -m1 '^description:' "$f" || true)
  if [[ -z "$desc_line" ]]; then
    return # F3 already recorded the missing-field blocker; do not double-count.
  fi
  if [[ ! "$desc_line" =~ ^description:[[:space:]]*\"(.*)\"[[:space:]]*$ ]]; then
    FDf=$(( FDf + 1 ))
    echo "BLOCKER $rel: FD description value malformed (unbalanced quotes)" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
    return
  fi
  local desc_val="${BASH_REMATCH[1]}"
  # Literal JSON \uXXXX escapes leaking into prose is an unambiguous double-
  # encoding artifact (real sentences never contain them); a leading
  # backslash-quote is the same double-encoding signature. Legitimate
  # escaped quotes INSIDE prose (e.g. lamport.md: \"when\") are not flagged
  # — only the corruption signature is.
  if [[ "$desc_val" =~ \\u[0-9A-Fa-f]{4} || "$desc_val" == '\"'* ]]; then
    FDf=$(( FDf + 1 ))
    echo "BLOCKER $rel: FD description has broken JSON-escaping artifact (\\uXXXX or leading \\\") — value: ${desc_val:0:60}" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
  elif [[ ${#desc_val} -lt $FD_MIN_LEN ]]; then
    FDf=$(( FDf + 1 ))
    echo "BLOCKER $rel: FD description too short (${#desc_val} < $FD_MIN_LEN chars) — value: $desc_val" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
  else
    FDp=$(( FDp + 1 ))
  fi
}

# check_tools_nonempty — F9: tools list must have >=1 entry (recognises both
# YAML-list `  - X` and inline `tools: [A, B]` forms). Split out of
# check_file() to keep that function under coding-standards.md §4.2 (50 lines).
check_tools_nonempty() {
  local f="$1" rel="$2"
  if awk '
    /^tools:[[:space:]]*\[[^]]*[A-Za-z]+[^]]*\]/ { print; n++; exit }
    /^tools:/ { flag=1; next }
    flag && /^[a-z_]+:/ { flag=0 }
    flag && /^  *-/ { n++ }
    END { exit (n>0?0:1) }
  ' "$f" >/dev/null; then
    F9p=$(( F9p + 1 ))
  else
    F9f=$(( F9f + 1 ))
    echo "BLOCKER $rel: F9 tools list empty (per past lesson, agents fail on commit)" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
  fi
}

# check_genius_extras — G1/G2/G3: genius-only shapes field, citation pattern,
# <revolution> section. Split out of check_file() (same §4.2 reason as above).
check_genius_extras() {
  local f="$1" rel="$2"
  if grep -qE '^shapes:' "$f"; then G1p=$(( G1p + 1 )); else G1f=$(( G1f + 1 )); echo "WARNING $rel: G1 missing shapes field" >> "$WARNINGS_FILE"; warnings=$(( warnings + 1 )); fi
  if grep -qE '(Primary sources?:|^- [A-Z][a-z]+,? [A-Z]\.|[12][0-9]{3}\)\.|et al\.,? [12][0-9]{3})' "$f"; then
    G2p=$(( G2p + 1 ))
  else
    G2f=$(( G2f + 1 ))
    echo "BLOCKER $rel: G2 no citation pattern (zetetic source discipline)" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
  fi
  if grep -q '<revolution>' "$f"; then G3p=$(( G3p + 1 )); else G3f=$(( G3f + 1 )); echo "WARNING $rel: G3 missing <revolution> section" >> "$WARNINGS_FILE"; warnings=$(( warnings + 1 )); fi
}

# check_move_scaffold — B2/B3: Move-anchor presence and depth, with a
# structural scribe exemption. An agent whose body declares a <procedure>
# scaffold instead of <canonical-moves>/"Move N" is a single-purpose,
# budgeted scribe (e.g. memory-writer.md) by deliberate design, not a
# reasoning agent that forgot its Moves. Detection is structural — the
# file's own body says so via <procedure> — not a hardcoded name list;
# this schema has no kind:/agent_type: frontmatter field to key off
# instead. Absence of <procedure> leaves B2/B3 exactly as before, so a
# real reasoning agent missing Move 1 still blocks. Split out of
# check_file() to keep that function under coding-standards.md §4.2 (50
# lines). source: issue #21 follow-up, coordinator decision 2026-07-15.
check_move_scaffold() {
  local f="$1" rel="$2"
  if grep -q '<procedure>' "$f"; then
    return # scribe-kind: B2/B3 exempt, no pass/fail tallied
  fi

  # B2 Move 1
  if grep -qE '^\*\*Move 1' "$f"; then B2p=$(( B2p + 1 )); else B2f=$(( B2f + 1 )); echo "BLOCKER $rel: B2 missing 'Move 1' anchor" >> "$BLOCKERS_FILE"; blockers=$(( blockers + 1 )); fi

  # B3 >=3 Moves
  local mv; mv=$(grep -cE '^\*\*Move [0-9]+' "$f" || true)
  if [[ "$mv" -ge 3 ]]; then
    B3p=$(( B3p + 1 ))
  else
    B3f=$(( B3f + 1 ))
    echo "WARNING $rel: B3 only $mv Move(s) — depth shallow" >> "$WARNINGS_FILE"
    warnings=$(( warnings + 1 ))
  fi
}

check_file() {
  local f="$1" kind="$2"
  local rel; rel="${f#"$ROOT"/}"
  files=$(( files + 1 ))

  # F1
  if [[ "$(head -n1 "$f")" == "---" ]]; then
    F1p=$(( F1p + 1 ))
  else
    F1f=$(( F1f + 1 ))
    echo "BLOCKER $rel: F1 missing frontmatter ---" >> "$BLOCKERS_FILE"
    blockers=$(( blockers + 1 ))
  fi

  check_fm "$f" "$rel" name        F2p F2f BLOCKER
  check_fm "$f" "$rel" description  F3p F3f BLOCKER
  check_fm "$f" "$rel" model        F4p F4f WARNING
  check_fm "$f" "$rel" effort       F5p F5f WARNING
  check_fm "$f" "$rel" when_to_use  F6p F6f BLOCKER
  check_fm "$f" "$rel" agent_topic  F7p F7f BLOCKER
  check_fm "$f" "$rel" tools        F8p F8f BLOCKER
  check_tools_nonempty "$f" "$rel"
  check_description_quality "$f" "$rel"

  # B1 identity
  if grep -q '<identity>' "$f"; then B1p=$(( B1p + 1 )); else B1f=$(( B1f + 1 )); echo "BLOCKER $rel: B1 missing <identity>" >> "$BLOCKERS_FILE"; blockers=$(( blockers + 1 )); fi

  check_move_scaffold "$f" "$rel"

  [[ "$kind" == "genius" ]] && check_genius_extras "$f" "$rel"

  # P1 collaboration
  if grep -qiE '(Pair (with|Dijkstra|Lamport|engineer)|Distinct from|Hand off|hand-?off)' "$f"; then
    P1p=$(( P1p + 1 ))
  else
    P1f=$(( P1f + 1 ))
    echo "WARNING $rel: P1 no pairing/handoff hint in body" >> "$WARNINGS_FILE"
    warnings=$(( warnings + 1 ))
  fi
}

for f in "$TEAM_DIR"/*.md; do
  [[ -f "$f" ]] || continue
  check_file "$f" "team"
done

for f in "$GEN_DIR"/*.md; do
  [[ -f "$f" ]] || continue
  [[ "$(basename "$f")" == "INDEX.md" ]] && continue
  check_file "$f" "genius"
done

# An audit that audits nothing is not a passing audit — it is a silent no-op
# masquerading as a green check (the exact failure mode reported in issue
# #21). Fail loudly and explicitly rather than printing an empty report and
# exiting 0.
if [[ "$files" -eq 0 ]]; then
  echo "ERROR: agent-definition-auditor matched 0 files under ROOT='$ROOT'" >&2
  echo "       (TEAM_DIR=$TEAM_DIR, GEN_DIR=$GEN_DIR)" >&2
  echo "       Silence is not success: an audit that finds nothing to audit is a failure, not a pass." >&2
  rm -f "$BLOCKERS_FILE" "$WARNINGS_FILE"
  exit 2
fi

echo "============================================================"
echo "AGENT DEFINITION AUDIT  ($files files)"
echo "============================================================"
printf "%-4s %-7s %-7s\n" "CHK" "PASS" "FAIL"
for c in $CHECKS; do
  eval "p=\$${c}p; f=\$${c}f"
  printf "%-4s %-7d %-7d\n" "$c" "$p" "$f"
done
echo ""
echo "Total blockers: $blockers"
echo "Total warnings: $warnings"
echo ""
if [[ -s "$BLOCKERS_FILE" ]]; then
  echo "--- BLOCKERS ---"
  sort "$BLOCKERS_FILE"
  echo ""
fi
if [[ -s "$WARNINGS_FILE" ]]; then
  echo "--- WARNINGS ---"
  sort "$WARNINGS_FILE"
fi

rm -f "$BLOCKERS_FILE" "$WARNINGS_FILE"
[[ "$blockers" -eq 0 ]] && exit 0 || exit 1
