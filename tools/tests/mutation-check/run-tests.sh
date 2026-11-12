#!/usr/bin/env bash
# Regression tests for the Python runner of tools/mutation_check.sh (run_python).
#
# Proves, with a stand-in `mutmut` on PATH that lists N surviving mutants one
# line at a time, as a Python CLI does:
#   (a) no survivor -> exit 0;
#   (b) a few survivors -> exit 1, and the gate names them;
#   (c) a long listing -> exit 1. The gate used to read
#       `mutmut results | grep -iq survived` under pipefail: grep left at its
#       first match, mutmut died of a broken pipe, the pipeline was non-zero and
#       the gate printed "0 surviving mutants" over a listing full of them;
#   (d) pyproject.toml is restored byte for byte after each run.
set -euo pipefail
cd "$(dirname "$0")"
CHECK="$(cd ../.. && pwd)/mutation_check.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
check() { local name="$1" cond="$2"; if [ "$cond" = 1 ]; then echo "  PASS: $name"; PASS=$((PASS+1));
          else echo "  FAIL: $name"; FAIL=$((FAIL+1)); fi; }

echo "mutation-check regression tests"

mkdir -p "$TMP/bin" "$TMP/repo/pkg" "$TMP/repo/tests"
cat >"$TMP/bin/mutmut" <<'STUB'
#!/bin/sh
# `run` does nothing; `results` prints $FAKE_SURVIVORS lines, one per mutant.
case "$1" in
  run) exit 0 ;;
  results) exec python3 -c "
import sys
for i in range(int(sys.argv[1])): print('    pkg.x.x_f__mutmut_%d: survived' % i)" "${FAKE_SURVIVORS:-0}" ;;
esac
exit 2
STUB
chmod +x "$TMP/bin/mutmut"
printf '[tool.mutmut]\nonly_mutate = ["pkg"]\npytest_add_cli_args_test_selection = ["tests"]\n' >"$TMP/repo/pyproject.toml"
cp "$TMP/repo/pyproject.toml" "$TMP/pyproject.before"
echo 'def f(): return 1' >"$TMP/repo/pkg/x.py"
echo 'def test_f(): pass' >"$TMP/repo/tests/test_x.py"

# gate <survivors>: exit code in CODE, stderr in $TMP/err.
gate() {
  set +e
  (cd "$TMP/repo" && FAKE_SURVIVORS="$1" PATH="$TMP/bin:$PATH" \
     bash "$CHECK" --tests tests/test_x.py pkg/x.py >"$TMP/out" 2>"$TMP/err")
  CODE=$?
  set -e
}

gate 0
check "no-survivor-exit-0" "$([ "$CODE" = 0 ] && echo 1 || echo 0)"

gate 3
check "three-survivors-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
check "three-survivors-named" "$([ "$(grep -c ': survived$' "$TMP/err")" = 3 ] && echo 1 || echo 0)"

# source: measured 2026-11-12 on the gate before the fix: with 2000 survivors it
# exited 0 in 50 of 50 runs, with and without PYTHONUNBUFFERED.
gate 2000
check "long-listing-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
check "long-listing-named" "$([ "$(grep -c ': survived$' "$TMP/err")" = 2000 ] && echo 1 || echo 0)"

check "pyproject-restored" "$(cmp -s "$TMP/repo/pyproject.toml" "$TMP/pyproject.before" && echo 1 || echo 0)"

echo "mutation-check: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
