#!/usr/bin/env bash
# tests/run-all.sh — the one command that runs every suite in this repository.
#
# Why this exists (issue #73): CONTRIBUTING.md documented five test scripts, none
# of which existed. A contributor's first command failed with "No such file or
# directory". The list had been hand-maintained beside the tree and drifted.
#
# So the list is DISCOVERED, never written down: every suite is found by glob at
# run time. A suite added under tools/tests/ or scripts/ is picked up with no
# edit here and no edit in CONTRIBUTING.md, and tools/doc-command-check.sh gates
# the docs against what this script reports.
#
# Usage:
#   bash tests/run-all.sh          run every suite, exit non-zero if any fails
#   bash tests/run-all.sh --list   print the discovered suites, run nothing
#
# Exit: 0 only if every discovered suite passed. Fails closed — a suite that
# cannot run (missing pytest, no suites discovered) is a failure, not a skip.
# An audit that audits nothing is not a passing audit.

set -uo pipefail   # NOT -e: suites are run and their exit codes collected.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to repo root $REPO_ROOT" >&2; exit 1; }

# Python interpreter used for the pytest suite. Overridable so a contributor
# whose default python3 lacks pytest can point at one that has it.
PYTHON_BIN="${PYTHON_BIN:-python3}"

list_shell_suites() {
  local s
  for s in tools/tests/*/run-tests.sh; do
    [[ -f "$s" ]] && printf '%s\n' "$s"
  done
  for s in scripts/test-*.sh; do
    [[ -f "$s" ]] && printf '%s\n' "$s"
  done
}

# Orphan detection (issue #93): list_shell_suites' glob only matches a
# run-tests.sh exactly one level under tools/tests/ (tools/tests/<suite>/
# run-tests.sh). A suite nested deeper (tools/tests/<suite>/<sub>/run-tests.sh)
# would exist on disk, look like coverage, and never actually run -- silently
# reproducing the "registered nowhere" bug this discovery mechanism was built
# to prevent. Compare disk against discovery and fail closed on a mismatch.
check_no_orphan_suites() {
  local on_disk discovered orphans
  on_disk="$(find tools/tests -name 'run-tests.sh' 2>/dev/null | sort)"
  discovered="$(list_shell_suites | grep '^tools/tests/' | sort)"
  orphans="$(comm -23 <(printf '%s\n' "$on_disk") <(printf '%s\n' "$discovered"))"
  if [[ -n "$orphans" ]]; then
    echo "FATAL: run-tests.sh exists on disk but is not discovered by tools/tests/*/run-tests.sh:" >&2
    printf '%s\n' "$orphans" | sed 's/^/  /' >&2
    echo "       Move it to tools/tests/<suite-name>/run-tests.sh (exactly one level deep)," >&2
    echo "       or it will never run locally or in CI." >&2
    return 1
  fi
  return 0
}

if [[ "${1:-}" == "--list" ]]; then
  check_no_orphan_suites || exit 2
  printf '%s\n' "$PYTHON_BIN -m pytest"
  list_shell_suites
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  echo "usage: bash tests/run-all.sh [--list]" >&2
  exit 2
fi

passed=0
failed=0
failed_names=""

run_suite() {
  # $1 = human label, remaining args = the command to run.
  local label="$1"; shift
  printf '=== %s\n' "$label"
  if "$@" > /tmp/run-all-suite.$$ 2>&1; then
    passed=$(( passed + 1 ))
    printf '    ok\n'
  else
    failed=$(( failed + 1 ))
    failed_names="${failed_names}
  $label"
    printf '    FAILED (last 20 lines):\n'
    tail -20 /tmp/run-all-suite.$$ | sed 's/^/    | /'
  fi
  rm -f /tmp/run-all-suite.$$
}

echo "============================================================"
echo "ALL SUITES  (repo: $REPO_ROOT)"
echo "============================================================"

check_no_orphan_suites || exit 2

# 1. Python suite. Absence of pytest is reported as a failure, not skipped:
# a green run that silently omitted 334 tests is the failure mode this whole
# script exists to prevent.
if "$PYTHON_BIN" -c 'import pytest' 2>/dev/null; then
  run_suite "pytest (tests/)" "$PYTHON_BIN" -m pytest -q
else
  failed=$(( failed + 1 ))
  failed_names="${failed_names}
  pytest (tests/) — pytest is not installed for '$PYTHON_BIN'"
  printf '=== pytest (tests/)\n    FAILED: pytest is not installed for %s\n' "$PYTHON_BIN"
  printf '    Install it (pip install pytest) or set PYTHON_BIN to an interpreter that has it.\n'
fi

# 2. Shell suites, discovered by glob.
suite_count=0
while IFS= read -r suite; do
  [[ -z "$suite" ]] && continue
  suite_count=$(( suite_count + 1 ))
  run_suite "$suite" bash "$suite"
done < <(list_shell_suites)

if [[ "$suite_count" -eq 0 ]]; then
  echo "FATAL: discovered 0 shell suites under tools/tests/ and scripts/." >&2
  echo "       Silence is not success: a runner that finds nothing to run has failed." >&2
  exit 2
fi

echo ""
echo "============================================================"
printf 'RESULT: %d passed, %d failed\n' "$passed" "$failed"
if [[ "$failed" -gt 0 ]]; then
  printf 'Failed suites:%s\n' "$failed_names"
  exit 1
fi
echo "============================================================"
exit 0
