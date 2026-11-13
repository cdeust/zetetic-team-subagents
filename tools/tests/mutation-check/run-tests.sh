#!/usr/bin/env bash
# Regression tests for the Python runner of tools/mutation_check.sh (run_python).
#
# Proves, with a stand-in `mutmut` on PATH that lists N mutants one line at a
# time, as a Python CLI does, with the status and exit codes the case sets:
#   (a) every mutant killed -> exit 0;
#   (b) a few survivors -> exit 1, and the gate names them;
#   (c) a long listing -> exit 1. The gate used to read
#       `mutmut results | grep -iq survived` under pipefail: grep left at its
#       first match, mutmut died of a broken pipe, the pipeline was non-zero and
#       the gate printed "0 surviving mutants" over a listing full of them;
#   (d) once the runs are over, pyproject.toml is byte for byte what it was;
#   (e) mutants no test reaches ("no tests") -> exit 1, named;
#   (f) mutants left "not checked" (the clean test run failed) -> exit 5, no verdict;
#   (g) an empty listing (no mutant in the changed code) -> exit 0, said as such;
#   (h) a listing command that fails -> exit 5, no verdict;
#   (i) a status printed with a capital ("Survived", "Not checked") is read as
#       the same status: exit 1 and exit 5, never a pass;
#   (j) --help prints the whole header, exit codes 4 and 5 included, and stops
#       before the first line of code.
# source: the statuses and exit codes are those of mutmut 3.8.1, measured
# 2026-11-12: "survived", "no tests", "not checked", "killed"; `mutmut results
# --all true` exits 0 in each case; `mutmut run` exits 1 when the clean test run
# fails and when the code holds no mutant.
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
# `run` exits $FAKE_RUN_RC; `results` prints $FAKE_MUTANTS lines, one per mutant,
# with the status $FAKE_STATUS, and exits $FAKE_RESULTS_RC.
case "$1" in
  run) exit "${FAKE_RUN_RC:-0}" ;;
  results) python3 -c "
import sys
for i in range(int(sys.argv[1])): print('    pkg.x.x_f__mutmut_%d: %s' % (i, sys.argv[2]))" "${FAKE_MUTANTS:-0}" "${FAKE_STATUS:-survived}"
    exit "${FAKE_RESULTS_RC:-0}" ;;
esac
exit 2
STUB
chmod +x "$TMP/bin/mutmut"
printf '[tool.mutmut]\nonly_mutate = ["pkg"]\npytest_add_cli_args_test_selection = ["tests"]\n' >"$TMP/repo/pyproject.toml"
cp "$TMP/repo/pyproject.toml" "$TMP/pyproject.before"
echo 'def f(): return 1' >"$TMP/repo/pkg/x.py"
echo 'def test_f(): pass' >"$TMP/repo/tests/test_x.py"

# gate <mutants> [status] [run rc] [results rc]: exit code in CODE, stdout in
# $TMP/out, stderr in $TMP/err.
gate() {
  set +e
  (cd "$TMP/repo" && FAKE_MUTANTS="$1" FAKE_STATUS="${2:-survived}" FAKE_RUN_RC="${3:-0}" \
     FAKE_RESULTS_RC="${4:-0}" PATH="$TMP/bin:$PATH" \
     bash "$CHECK" --tests tests/test_x.py pkg/x.py >"$TMP/out" 2>"$TMP/err")
  CODE=$?
  set -e
}

gate 3 killed
check "all-killed-exit-0" "$([ "$CODE" = 0 ] && echo 1 || echo 0)"
check "all-killed-said" "$(grep -q '0 surviving mutants' "$TMP/out" && echo 1 || echo 0)"

gate 3
check "three-survivors-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
check "three-survivors-named" "$([ "$(grep -c ': survived$' "$TMP/err")" = 3 ] && echo 1 || echo 0)"

# source: 20000 lines of this stand-in are 748890 bytes, eleven times the 65536 a
# Linux pipe holds (pipe(7)): a producer piped into `grep -q` is still writing
# when grep leaves, whatever the timing. With 2000 lines (72890 bytes) the gate
# before the fix exited 0 in 100 of 100 runs on one machine, with 7 kB to spare.
gate 20000
check "long-listing-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
check "long-listing-named" "$([ "$(grep -c ': survived$' "$TMP/err")" = 20000 ] && echo 1 || echo 0)"

gate 2 "no tests"
check "untested-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
check "untested-named" "$([ "$(grep -c ': no tests$' "$TMP/err")" = 2 ] && echo 1 || echo 0)"

gate 4 "not checked" 1
check "unchecked-exit-5" "$([ "$CODE" = 5 ] && echo 1 || echo 0)"
check "unchecked-counted" "$(grep -q 'left 4 mutant(s) unchecked (mutmut run exited 1)' "$TMP/err" && echo 1 || echo 0)"

gate 0 survived 1
check "no-mutant-exit-0" "$([ "$CODE" = 0 ] && echo 1 || echo 0)"
check "no-mutant-said" "$(grep -q 'no mutant in the changed code' "$TMP/out" && echo 1 || echo 0)"

gate 3 survived 0 2
check "listing-failed-exit-5" "$([ "$CODE" = 5 ] && echo 1 || echo 0)"

gate 2 "Survived"
check "capital-survived-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
gate 2 "No tests"
check "capital-no-tests-exit-1" "$([ "$CODE" = 1 ] && echo 1 || echo 0)"
gate 3 "Not checked" 1
check "capital-unchecked-exit-5" "$([ "$CODE" = 5 ] && echo 1 || echo 0)"

bash "$CHECK" --help >"$TMP/help" 2>&1 || true
check "help-lists-exit-4" "$(grep -q '^  4  the per-repo config' "$TMP/help" && echo 1 || echo 0)"
check "help-lists-exit-5" "$(grep -q '^  5  no verdict' "$TMP/help" && echo 1 || echo 0)"
check "help-stops-before-code" "$(grep -q 'set -euo pipefail' "$TMP/help" && echo 0 || echo 1)"

check "pyproject-restored" "$(cmp -s "$TMP/repo/pyproject.toml" "$TMP/pyproject.before" && echo 1 || echo 0)"

echo "mutation-check: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
