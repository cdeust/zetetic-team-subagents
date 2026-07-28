#!/usr/bin/env bash
# Regression suite for tools/doc-count-check.sh (issue #72).
#
# The gate has two failure modes it must catch, and the second is the one that
# lets drift back in:
#   1. a document states a number the tree does not support (DRIFT);
#   2. a document is reworded so a registered pattern matches nothing, leaving
#      the claim silently unchecked (UNMATCHED).
# A gate that only caught (1) would decay into a gate that checks nothing, which
# is how four files came to disagree in the first place.
#
# The suite also pins the two extraction bugs found while building the gate,
# because both produced a WRONG number rather than an error: greedy matching
# read "97" as "7", and a literal pipe in a pattern degraded to ERE alternation.
#
# The drift and unmatched cases are driven by editing README.md IN PLACE and
# restoring it, deliberately: pointing the checker at a mock document would test
# a mock registry, and the registry is the part that rots. The edit window is one
# checker invocation, restoration is trapped on EXIT/INT/TERM/HUP, and the file
# is verified byte-for-byte afterwards by checksum. If restoration ever fails the
# suite says so and names the preserved copy rather than exiting quietly.

set -uo pipefail

cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
CHECKER="$REPO/tools/doc-count-check.sh"

pass=0
fail=0
ok()  { pass=$(( pass + 1 )); printf '  ok   %s\n' "$1"; }
bad() { fail=$(( fail + 1 )); printf '  FAIL %s\n' "$1"; }

# --- The measured quantities must be internally consistent -------------------
report="$(bash "$CHECKER" --report 2>&1)"
rc=$?
if [[ $rc -ne 0 ]]; then
  bad "--report exits 0 (got $rc)"
  printf '%s\n' "$report" | sed 's/^/       | /'
else
  ok "--report exits 0"
fi

q() { printf '%s' "$report" | awk -v k="$1" '$1==k {print $2}'; }

genius="$(q genius_agents)"; team="$(q team_agents)"; total="$(q agents_total)"
prob="$(q problem_skills)"; cat_="$(q category_skills)"; skills="$(q skills_total)"

if [[ -n "$genius" && -n "$team" && "$total" == "$(( genius + team ))" ]]; then
  ok "agents_total = genius_agents + team_agents ($genius + $team = $total)"
else
  bad "agents_total is not the sum of its two populations ($genius + $team != $total)"
fi

if [[ -n "$prob" && -n "$skills" && "$cat_" == "$(( skills - prob ))" ]]; then
  ok "category_skills = skills_total - problem_skills ($skills - $prob = $cat_)"
else
  bad "category_skills is not the remainder ($skills - $prob != $cat_)"
fi

for key in genius_agents team_agents agents_total problem_skills category_skills \
           skills_total hook_registrations hook_scripts commands tools suites memory_suites; do
  v="$(q "$key")"
  if [[ "$v" =~ ^[0-9]+$ ]] && [[ "$v" -gt 0 ]]; then
    ok "$key measured as a positive integer ($v)"
  else
    bad "$key did not measure to a positive integer (got '$v')"
  fi
done

# --- The extraction bugs, pinned ---------------------------------------------
# Both of these produced a wrong number rather than an error, so a test that only
# checked the exit code would have passed while the gate lied.
extract() {
  # $1 = regex, $2 = text. Mirrors the checker's extraction exactly.
  local d=$'\001'
  printf '%s\n' "$2" | sed -nE "s${d}.*${1}.*${d}\1${d}p"
}

got="$(extract '[^0-9]([0-9]+) genius agents' 'the 97 genius agents roster')"
if [[ "$got" == "97" ]]; then
  ok "greedy match guarded: '97 genius agents' extracts 97, not 7"
else
  bad "greedy match regression: extracted '$got', expected 97"
fi

got="$(extract '\| ([0-9]+) problem-shaped skills route you' '| **76 multi-step workflows** | 11 problem-shaped skills route you |')"
if [[ "$got" == "11" ]]; then
  ok "literal pipe in a pattern survives the sed delimiter"
else
  bad "pipe delimiter regression: extracted '$got', expected 11"
fi

# --- Drift and unmatched patterns must both fail -----------------------------
# Driven through the real checker by temporarily rewriting a real claim, so the
# test exercises the shipped registry rather than a mock of it.
README="$REPO/README.md"
backup="$(mktemp)"
cp "$README" "$backup"
# The suite edits a tracked file in place, so restoration is a correctness
# requirement, not tidiness. Trapped on the interrupt signals too, and VERIFIED
# by checksum afterwards: a suite that silently leaves README modified would
# corrupt the very artifact the gate reads.
restore() { cp "$backup" "$README"; }
trap restore EXIT INT TERM HUP
before_sum="$(shasum -a 256 < "$README" | awk '{print $1}')"

# 1. DRIFT: change a real number to a wrong one.
sed -i.bak "s|badge/agents-${total}-|badge/agents-999-|" "$README" && rm -f "$README.bak"
out="$(bash "$CHECKER" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && printf '%s' "$out" | grep -q "DRIFT.*agents_total claims 999"; then
  ok "a wrong number is reported as DRIFT and exits 1"
else
  bad "drift was not caught (exit $rc)"
  printf '%s\n' "$out" | sed 's/^/       | /'
fi
restore
cp "$README" "$backup"

# 2. UNMATCHED: reword the copy so the pattern no longer matches.
sed -i.bak "s|badge/agents-${total}-|badge/AGENTS-${total}-|" "$README" && rm -f "$README.bak"
out="$(bash "$CHECKER" 2>&1)"; rc=$?
if [[ $rc -eq 1 ]] && printf '%s' "$out" | grep -q "UNMATCHED.*agents_total"; then
  ok "reworded copy is reported as UNMATCHED and exits 1, not silently unchecked"
else
  bad "reworded copy did not fail the gate (exit $rc)"
  printf '%s\n' "$out" | sed 's/^/       | /'
fi
restore
trap - EXIT INT TERM HUP
after_sum="$(shasum -a 256 < "$README" | awk '{print $1}')"
if [[ "$before_sum" == "$after_sum" ]]; then
  ok "README restored byte-for-byte after the in-place drift tests"
  rm -f "$backup"
else
  bad "README was NOT restored; the pre-test copy is preserved at $backup"
fi

# --- Usage and the real tree -------------------------------------------------
out="$(bash "$CHECKER" --nonsense 2>&1)"; rc=$?
if [[ $rc -eq 2 ]]; then ok "an unknown argument exits 2"; else bad "unknown argument should exit 2 (got $rc)"; fi

if bash "$CHECKER" >/dev/null 2>&1; then
  ok "the repository's own documents all agree with the tree"
else
  bad "the repository's own documents disagree with the tree"
  bash "$CHECKER" 2>&1 | sed 's/^/       | /'
fi

echo ""
printf 'doc-count-check result: %d passed, %d failed\n' "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  echo "doc-count-check FAILED"
  exit 1
fi
echo "doc-count-check PASSED"
exit 0
