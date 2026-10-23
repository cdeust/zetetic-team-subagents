#!/usr/bin/env bash
# Regression suite for templates/ci/pipeline.yml, the single CI template
# (docs/superpowers/specs/2026-10-22-single-ci-design.md).

#   T1  the template exists
#   T2  actionlint accepts it (expressions, needs graph, shellcheck of run:)
#   T3  no `uses:` names a reusable workflow or this repository
#   T4  the two inline python steps are the tools, byte for byte (pytest)

# Fails closed: a missing linter is a failure, not a skip.
set -uo pipefail

cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }
REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
TEMPLATE="$REPO/templates/ci/pipeline.yml"
# source: tests/run-all.sh, the same override for the pytest interpreter.
PYTHON_BIN="${PYTHON_BIN:-python3}"

pass=0
fail=0
ok()  { pass=$(( pass + 1 )); printf '  ok   %s\n' "$1"; }
bad() { fail=$(( fail + 1 )); printf '  FAIL %s\n' "$1"; }

# T1
if [[ -f "$TEMPLATE" ]]; then ok "template exists"; else bad "template missing: $TEMPLATE"; fi

# T2: use the same hash-locked test environment as pytest. actionlint-py
# installs the official binary into Python's scripts directory, not a module.
lint() {
  local scripts_dir
  scripts_dir="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_path("scripts"))')" || return
  if [[ -x "$scripts_dir/actionlint" ]]; then "$scripts_dir/actionlint" "$@"
  elif command -v actionlint >/dev/null 2>&1; then actionlint "$@"
  else echo "actionlint missing: install requirements-dev.lock with $PYTHON_BIN" >&2; return 2; fi
}
if [[ -f "$TEMPLATE" ]]; then
  out="$(lint "$TEMPLATE" 2>&1)"; rc=$?
  if [[ $rc -eq 0 ]]; then ok "actionlint passes"; else bad "actionlint rc=$rc"; printf '%s\n' "$out" | sed 's/^/       | /'; fi
fi

# T3: the rendered file calls nothing in another repository at run time.
if [[ -f "$TEMPLATE" ]]; then
  if grep -nE '^\s*uses:\s*.*(\.github/workflows/|zetetic-team-subagents)' "$TEMPLATE"; then
    bad "a uses: references a reusable workflow or the template repository"
  else ok "no reusable workflow, no reference to the template repository"; fi
fi

# T4 belongs to unit in the CI partition; standalone retains the full check.
# Source: ci.json unit and tests/run-all.sh --group regression.
if [[ "${RUN_ALL_GROUP:-all}" == regression ]]; then
  echo "  Python template assertions are owned by the unit category."
else
  if (cd "$REPO" && "$PYTHON_BIN" -m pytest -q tests/test_ci_template.py >/dev/null 2>&1); then
    ok "tests/test_ci_template.py passes"
  else bad "tests/test_ci_template.py fails (run: $PYTHON_BIN -m pytest -q tests/test_ci_template.py)"; fi
fi

printf '\nci-template: %d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
