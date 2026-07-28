#!/usr/bin/env bash
# Regression suite for tools/doc-command-check.sh (issue #73).
#
# The gate's whole value is that it FAILS when a document names a command the
# repo does not ship — the condition that shipped undetected for five commands
# in CONTRIBUTING.md. So the suite asserts the failing path first and hardest,
# then the classes of token that must NOT be reported (host paths, placeholders,
# module invocations, session transcripts), because a gate with false positives
# gets ignored and stops gating.
#
# Self-contained: builds throwaway markdown fixtures in a tmpdir and points the
# checker at them by argument. Never edits the repo's own docs.

set -uo pipefail   # NOT -e: the checker is deliberately run expecting exit 1.

cd "$(dirname "$0")" || { echo "FATAL: cannot cd to suite directory $(dirname "$0")" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null || (cd ../../.. && pwd))"
CHECKER="$REPO/tools/doc-command-check.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok()   { pass=$(( pass + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { fail=$(( fail + 1 )); printf '  FAIL %s\n' "$1"; }

# assert_run <label> <expected-exit> <fixture-body...>
# Writes the body to a fixture inside the repo tree (so relative paths resolve
# the way the checker resolves them: against the repo root), runs the checker
# against it, and compares the exit code.
assert_run() {
  local label="$1" want="$2" body="$3" extra_grep="${4:-}"
  local fixture="$REPO/.doc-command-check-fixture.md"
  printf '%s\n' "$body" > "$fixture"
  local out rc
  out="$(bash "$CHECKER" "$fixture" 2>&1)"; rc=$?
  rm -f "$fixture"
  if [[ "$rc" -ne "$want" ]]; then
    bad "$label (expected exit $want, got $rc)"
    printf '%s\n' "$out" | sed 's/^/       | /'
    return
  fi
  if [[ -n "$extra_grep" ]] && ! printf '%s' "$out" | grep -q "$extra_grep"; then
    bad "$label (exit $rc correct, but output lacked '$extra_grep')"
    printf '%s\n' "$out" | sed 's/^/       | /'
    return
  fi
  ok "$label"
}

echo "=== doc-command-check suite ==="

# --- The failing path: the defect this gate exists to catch ------------------
assert_run "missing script is reported and fails" 1 '```bash
bash tests/test-does-not-exist.sh
```' "tests/test-does-not-exist.sh"

assert_run "an existing script passes" 0 '```bash
bash tests/run-all.sh
```'

assert_run "one missing among several still fails" 1 '```bash
bash tests/run-all.sh
bash tools/doc-command-check.sh
bash tools/not-a-real-tool.sh
```' "tools/not-a-real-tool.sh"

# --- Fence discipline: prose is not scanned ----------------------------------
assert_run "a command in PROSE is not checked" 2 'Run bash tests/nope.sh sometime.

No fenced block here at all.'

# --- Token classes that must NOT be reported ---------------------------------
assert_run "host path under ~ is not a repo claim" 2 '```bash
bash ~/.claude/plugins/whatever.sh
```'

assert_run "absolute path is not a repo claim" 2 '```bash
bash /usr/local/bin/whatever.sh
```'

assert_run "placeholder in angle brackets is not a repo claim" 2 '```bash
bash <repo>/tools/zetetic-checker.sh
```'

assert_run "shell variable is not a repo claim" 2 '```bash
bash "$REPO"/tools/zetetic-checker.sh
```'

assert_run "python3 -m module form is skipped" 2 '```bash
python3 -m pytest -q
```'

assert_run "python3 -c inline code is skipped" 2 '```bash
python3 -c "import sys; print(sys.version)"
```'

assert_run "prompt-prefixed transcript is not an instruction" 2 '```
$ python bench/retry_window.py
  1.0s: 91.2%
```'

assert_run "flags before the operand are stepped over" 1 '```bash
bash -x tests/test-does-not-exist.sh
```' "tests/test-does-not-exist.sh"

# --- Fail-closed behaviour ---------------------------------------------------
out="$(bash "$CHECKER" "$TMP/nonexistent-doc.md" 2>&1)"; rc=$?
if [[ "$rc" -eq 2 ]] && printf '%s' "$out" | grep -q "not found"; then
  ok "a missing document is a hard error, not a silent pass"
else
  bad "a missing document should exit 2 (got $rc)"
fi

# --- The real tree must be clean ---------------------------------------------
if bash "$CHECKER" > "$TMP/real.out" 2>&1; then
  ok "the repository's own documents all resolve"
else
  bad "the repository's own documents have a broken command"
  sed 's/^/       | /' "$TMP/real.out"
fi

echo ""
printf 'doc-command-check result: %d passed, %d failed\n' "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  echo "doc-command-check FAILED"
  exit 1
fi
echo "doc-command-check PASSED"
exit 0
