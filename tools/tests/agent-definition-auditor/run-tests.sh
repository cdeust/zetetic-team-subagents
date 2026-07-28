#!/usr/bin/env bash
# Regression suite — agent-definition-auditor.sh check FP (MCP tool prefixes).
#
# Root-cause incident (2026-07-27): Cortex renamed its plugin `cortex` ->
# `hypermnesia-mcp` in 4.15.0. The host derives a tool's name as
# `mcp__plugin_<plugin-name>_<mcp-server-key>__<tool>`, so the rename changed
# every Cortex tool name, and 122 files in this repo went on declaring the old
# ones. Nothing failed: an unresolvable tool name is dropped by the host, not
# reported, so the whole fleet silently lost recall and remember. FP exists to
# turn that silence into a failing gate. This suite proves:
#   1. current prefixes pass, and the tool exits 0 on an otherwise-clean file.
#   2. the pre-rename `mcp__plugin_cortex_cortex__` prefix is a BLOCKER.
#   3. any unknown plugin prefix blocks, not just the one that broke (the
#      check is not a hardcoded blocklist of one).
#   4. a file naming no MCP tool is NOT tallied as an FP pass — a check that
#      counts silence as success is how the original gap stayed invisible.
#   5. several distinct stale prefixes in one file each get their own blocker.
#
# Fixtures are copies of a real agent definition, mutated only at the MCP
# prefix, so every other check (F1-F9, FD, B1-B3, P1) passes and FP is what is
# under test. Self-contained: builds throwaway fixture trees in a tmpdir,
# never touches agents/. Exit non-zero if any assertion fails.
set -uo pipefail   # NOT -e: the stale-prefix invocations are expected to exit 1.
cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
AUDITOR="$REPO/tools/agent-definition-auditor.sh"
SAMPLE="$REPO/agents/engineer.md"
CURRENT_PREFIX="mcp__plugin_hypermnesia-mcp_cortex__"
STALE_PREFIX="mcp__plugin_cortex_cortex__"

PASS=0
FAIL=0
pass() { printf "  ok   %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  FAIL %s\n" "$1"; FAIL=$((FAIL + 1)); }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "agent-definition-auditor FP (MCP prefix) regression suite"

if [[ ! -f "$SAMPLE" ]]; then
  echo "  FAIL fixture source $SAMPLE missing" >&2
  exit 1
fi
if ! grep -q "$CURRENT_PREFIX" "$SAMPLE"; then
  echo "  FAIL fixture source names no MCP tool; FP would be untested" >&2
  exit 1
fi

# fp_row <output> -> the FP tally as "FP <pass> <fail>". The report is printf
# column-padded, so the fields are read positionally rather than string-matched.
fp_row() { grep -E '^FP ' <<<"$1" | awk '{print $1, $2, $3}'; }

# =====================================================================
# 1. Current prefixes pass.
# =====================================================================
echo " 1. current prefixes pass and the run exits 0:"
mkdir -p "$TMP/clean"
cp "$SAMPLE" "$TMP/clean/engineer.md"
out="$(bash "$AUDITOR" "$TMP/clean" 2>&1)"; rc=$?
[[ "$(fp_row "$out")" == "FP 1 0" ]] \
  && pass "FP tallies 1 pass, 0 fail" || fail "FP row was '$(fp_row "$out")'"
[[ "$rc" -eq 0 ]] && pass "exit 0" || fail "exit was $rc"

# =====================================================================
# 2. The pre-rename prefix blocks.
# =====================================================================
echo " 2. the pre-rename cortex prefix is a blocker:"
mkdir -p "$TMP/stale"
sed "s/$CURRENT_PREFIX/$STALE_PREFIX/g" "$SAMPLE" > "$TMP/stale/engineer.md"
out="$(bash "$AUDITOR" "$TMP/stale" 2>&1)"; rc=$?
grep -q "FP unknown MCP tool prefix '$STALE_PREFIX'" <<<"$out" \
  && pass "blocker names the stale prefix" || fail "no blocker for $STALE_PREFIX"
[[ "$(fp_row "$out")" == "FP 0 1" ]] \
  && pass "FP tallies 0 pass, 1 fail" || fail "FP row was '$(fp_row "$out")'"
[[ "$rc" -eq 1 ]] && pass "exit 1" || fail "exit was $rc"

# =====================================================================
# 3. Any unknown prefix blocks, not only the one that broke.
# =====================================================================
echo " 3. an unrelated unknown prefix also blocks:"
mkdir -p "$TMP/unknown"
sed "s/$CURRENT_PREFIX/mcp__plugin_not-installed_srv__/g" "$SAMPLE" \
  > "$TMP/unknown/engineer.md"
out="$(bash "$AUDITOR" "$TMP/unknown" 2>&1)"
grep -q "FP unknown MCP tool prefix 'mcp__plugin_not-installed_srv__'" <<<"$out" \
  && pass "blocker names the unknown prefix" || fail "unknown prefix not blocked"

# =====================================================================
# 4. No MCP tools named: not tallied either way (no pass by vacuity).
# =====================================================================
echo " 4. a file naming no MCP tool is not tallied as an FP pass:"
mkdir -p "$TMP/nomcp"
# Every MCP tool goes, not only the Cortex ones: engineer.md also names the
# automatised-pipeline server, and leaving it in would make FP tally a pass for
# a reason this case is not testing.
sed -E 's/mcp__plugin_[A-Za-z0-9_-]*__[a-z_]*/Read/g' "$SAMPLE" \
  > "$TMP/nomcp/engineer.md"
out="$(bash "$AUDITOR" "$TMP/nomcp" 2>&1)"
if grep -q 'mcp__plugin_' "$TMP/nomcp/engineer.md"; then
  fail "fixture still names an MCP tool; case 4 would be vacuous"
else
  pass "fixture names no MCP tool"
fi
[[ "$(fp_row "$out")" == "FP 0 0" ]] \
  && pass "FP tallies neither pass nor fail" || fail "FP row was '$(fp_row "$out")'"

# =====================================================================
# 5. Two distinct stale prefixes in one file: one blocker each.
# =====================================================================
echo " 5. each distinct stale prefix gets its own blocker:"
mkdir -p "$TMP/two"
sed -e "s/$CURRENT_PREFIX/$STALE_PREFIX/g" \
    -e "s/mcp__plugin_automatised-pipeline_automatised-pipeline__/mcp__plugin_ap_ap__/g" \
    "$SAMPLE" > "$TMP/two/engineer.md"
out="$(bash "$AUDITOR" "$TMP/two" 2>&1)"
n="$(grep -c "FP unknown MCP tool prefix" <<<"$out")"
[[ "$n" -eq 2 ]] && pass "2 blockers for 2 stale prefixes" || fail "got $n blockers, want 2"
[[ "$(fp_row "$out")" == "FP 0 1" ]] \
  && pass "the file is tallied failed once, not twice" || fail "FP row was '$(fp_row "$out")'"

echo ""
echo "passed: $PASS   failed: $FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
