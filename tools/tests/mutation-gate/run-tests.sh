#!/usr/bin/env bash
# Regression tests for tools/mutation-gate.sh — the loop-facing test-strength gate.
#
# Proves the proportional contract (the reason the wrapper exists):
#   (a) no files            -> exit 0 (PASS).
#   (b) only non-applicable (.md/.sh) changed -> exit 0 (PASS, nothing to test).
#   (c) applicable source, runner kills all   -> exit 0 (PASS).
#   (d) applicable source, a mutant SURVIVES  -> exit 1 (BLOCK — the only failure).
#   (e) applicable source, runner ABSENT (rc 3) -> exit 0 (degraded, loud warn).
#   (f) mixed languages, one survives          -> exit 1 (survivor dominates).
#   (g) --staged derives files from the index  -> exit 0 with nothing staged.
#
# Deterministic + tool-independent: a STUB mutation_check.sh (injected via
# MUTATION_CHECK_BIN) provides the registry() table AND a scripted exit code, so
# the test never needs a real mutation runner installed.
set -euo pipefail
cd "$(dirname "$0")"
GATE="$(cd ../.. && pwd)/mutation-gate.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
check() { local name="$1" cond="$2"; if [ "$cond" = 1 ]; then echo "  PASS: $name"; PASS=$((PASS+1));
          else echo "  FAIL: $name"; FAIL=$((FAIL+1)); fi; }

echo "mutation-gate regression tests"

# Stub runner: carries the SAME registry() shape mutation-gate parses for ext->lang,
# and exits per the file name so we can drive each branch:
#   *survive* -> exit 1 (surviving mutant)   *absent* -> exit 3 (no runner)
#   *noverdict* -> exit 5 (the runner could not decide)
#   otherwise -> exit 0 (all killed)
# NOTE: the inner registry heredoc MUST use the 'EOF' delimiter — the wrapper
# parses the runner's registry() with `sed -n "/<<'EOF'/,/^EOF/p"`. So the OUTER
# heredoc that writes the stub uses a different delimiter (STUBEOF).
STUB="$TMP/mutation_check.sh"
cat >"$STUB" <<'STUBEOF'
#!/usr/bin/env bash
registry() {
  cat <<'EOF'
python|.py|mutmut|pip install mutmut
typescript|.ts .tsx|stryker|npm i -D @stryker-mutator/core
EOF
}
# consume optional --tests <path>
[ "${1:-}" = "--tests" ] && shift 2
for a in "$@"; do
  case "$a" in *survive*) echo ">>> 1 surviving mutant"; exit 1 ;; esac
  case "$a" in *absent*) echo ">>> runner absent"; exit 3 ;; esac
  case "$a" in *noverdict*) echo ">>> mutants left unchecked"; exit 5 ;; esac
done
echo ">>> 0 surviving mutants"; exit 0
STUBEOF
chmod +x "$STUB"
export MUTATION_CHECK_BIN="$STUB"

# run <args...> -> echoes the gate's exit code; leaves output in $TMP/out
run() { local rc=0; MUTATION_GATE_TESTS=tests "$GATE" "$@" >"$TMP/out" 2>&1 || rc=$?; echo "$rc"; }
is()  { [ "$1" = "$2" ] && echo 1 || echo 0; }   # 1 iff equal (check's pass form)

check "no files -> exit 0"               "$(is "$(run)" 0)"
check "non-applicable (.md/.sh) -> exit 0" "$(is "$(run README.md install.sh)" 0)"
check "killed -> exit 0"                 "$(is "$(run src/ok.py)" 0)"
check "survivor -> exit 1 (BLOCK)"       "$(is "$(run src/survive.py)" 1)"
rc_absent="$(run src/absent.py)"
check "no runner -> exit 0 (degraded)"   "$(is "$rc_absent" 0)"
check "no runner -> loud UNVERIFIED warning" "$(grep -q UNVERIFIED "$TMP/out" && echo 1 || echo 0)"
rc_noverdict="$(run src/noverdict.py)"
check "no verdict -> exit 0 (degraded)"  "$(is "$rc_noverdict" 0)"
check "no verdict -> names rc=5, UNVERIFIED" "$(grep -q 'no verdict (rc=5).*UNVERIFIED' "$TMP/out" && echo 1 || echo 0)"
check "mixed langs w/ survivor -> exit 1" "$(is "$(run src/ok.ts src/survive.py)" 1)"
check "--staged empty -> exit 0"         "$(is "$(run --staged)" 0)"

echo "mutation-gate: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
