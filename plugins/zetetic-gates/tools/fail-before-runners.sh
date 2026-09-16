#!/usr/bin/env bash
# Runner selection and observable verdicts for fail-before-checker.sh.
# The interpreter of the CURRENT tree, so the base worktree borrows its
# dependencies: a fresh checkout has no virtual environment of its own, and a
# runner that cannot start would otherwise read as a test that failed.
resolve_python() {
  local root="$1"
  if [ -f "$root/uv.lock" ] && command -v uv >/dev/null 2>&1; then
    (cd "$root" && uv run --no-sync python -c "import sys; print(sys.executable)" 2>/dev/null) && return 0
  fi
  command -v python3 || true
}

# shellcheck disable=SC2034 # RUNNER is consumed by the sourcing checker.
# Fills RUNNER, an argv array so an interpreter path with spaces survives.
# Left empty when the tree declares no runner this gate understands.
detect_runner() {
  local root="$1" first="$2" python=""
  RUNNER=()
  case "$first" in
    *.py)
      python="$(resolve_python "$root")"
      [ -n "$python" ] || return 0
      "$python" -c "import pytest" 2>/dev/null || return 0
      RUNNER=("$python" -m pytest -q -p no:cacheprovider --tb=no -rA)
      ;;
    *.go) command -v go >/dev/null 2>&1 && RUNNER=(go test -v) ;;
    *.rs) command -v cargo >/dev/null 2>&1 && RUNNER=(cargo test) ;;
    *.ts | *.tsx | *.js) [ -f "$root/package.json" ] && command -v npm >/dev/null 2>&1 && RUNNER=(npm test --silent --) ;;
  esac
  # An absent runner is a finding for the caller, not a failed command: under
  # `set -e` a falsy last branch would kill the gate before it could say so.
  return 0
}

# Sources: https://pkg.go.dev/cmd/go#hdr-Test_packages
# https://doc.rust-lang.org/cargo/commands/cargo-test.html
# https://nodejs.org/api/test.html#test-reporters
# https://jestjs.io/docs/cli and https://vitest.dev/guide/reporters
nonpython_verdict() { # status
  local status="$1" passed="" failed=""
  case "${FILES[0]}" in
    *.go) passed='^--- PASS: '; failed='^--- FAIL: ' ;;
    *.rs) passed='^test result: ok\. [1-9][0-9]* passed;'; failed='^test result: FAILED\..* [1-9][0-9]* failed;' ;;
    *.ts | *.tsx | *.js)
      passed='^# pass [1-9][0-9]*$|Tests?:.*[1-9][0-9]* passed|Tests[[:space:]]+[1-9][0-9]* passed'
      failed='^# fail [1-9][0-9]*$|Tests?:.*[1-9][0-9]* failed|Tests[[:space:]]+[1-9][0-9]* failed'
      ;;
  esac
  if [ "$status" -eq 0 ] && [ -n "$passed" ] && grep -qE "$passed" "$RUN_OUTPUT"; then
    echo passed
  elif { [ "$status" -eq 1 ] || [ "$status" -eq 101 ]; } &&
      [ -n "$failed" ] && grep -qE "$failed" "$RUN_OUTPUT"; then
    echo failed
  fi
}

nonpython_targets() {
  local file
  for file in "${FILES[@]}"; do
    case "$file" in
      *.go) TARGETS+=("./$(dirname "$file")") ;;
      *.rs) TARGETS+=(--test "$(basename "$file" .rs)") ;;
      *) TARGETS+=("$file") ;;
    esac
  done
}
