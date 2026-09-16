#!/usr/bin/env bash
# fail-before-checker.sh — prove a new test can fail without the change it guards.
# Rationale, findings, configuration, limits: docs/fail-before.md.
# Principle enforced: rules/coding-standards.md §12.

set -euo pipefail

# Usage:
#   tools/fail-before-checker.sh                   # changed tests vs the upstream base
#   tools/fail-before-checker.sh --base <ref>      # ... vs an explicit ref
#   tools/fail-before-checker.sh --files <f1> ...  # ... only these test files

# Exit codes: 0 clean or non-blocking finding, 1 blocking finding, 2 usage error.
EXIT_CLEAN=0
EXIT_BLOCKED=1
EXIT_USAGE=2

# Wall-clock budget for the base-tree run; see docs/fail-before.md.
DEFAULT_TIMEOUT_SECONDS=120

usage() {
  sed -n '8,13p' "$0" >&2
  exit "$EXIT_USAGE"
}

repo_root() { git rev-parse --show-toplevel 2>/dev/null || return 1; }

# A file that lives in a test tree is a test, whatever it imports.
is_test_path() {
  case "$1" in
    */test_*.py | test_*.py | *_test.py) return 0 ;;
    */tests/*.py | */tests_py/*) return 0 ;;
    *.test.ts | *.test.tsx | *.test.js | *.spec.ts | *.spec.js) return 0 ;;
    */__tests__/*) return 0 ;;
    *_test.go) return 0 ;;
    */tests/*.rs) return 0 ;;
    *) return 1 ;;
  esac
}

conf_value() { # file key
  grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"' " || true
}

load_profile() {
  local conf="$1/.zetetic.conf" value
  ZETETIC_PROFILE="standard"
  TIMEOUT_SECONDS="$DEFAULT_TIMEOUT_SECONDS"
  [ -f "$conf" ] || return 0
  value="$(conf_value "$conf" ZETETIC_PROFILE)"
  [ -n "$value" ] && ZETETIC_PROFILE="$value"
  value="$(conf_value "$conf" ZETETIC_FAIL_BEFORE_TIMEOUT)"
  if [ -n "$value" ]; then
    case "$value" in
      '' | *[!0-9]*)
        echo "fail-before: ZETETIC_FAIL_BEFORE_TIMEOUT must be a whole number of seconds, got '$value'" >&2
        exit "$EXIT_USAGE"
        ;;
    esac
    TIMEOUT_SECONDS="$value"
  fi
  return 0
}

# Empty when the repository has no commit yet: there is no old tree to run
# the tests against, and the caller says so instead of aborting.
resolve_base() {
  git rev-parse --verify --quiet "@{upstream}" >/dev/null 2>&1 &&
    git merge-base HEAD "@{upstream}" 2>/dev/null && return 0
  git rev-parse --verify --quiet HEAD 2>/dev/null || true
}

changed_test_files() {
  local base="$1" file
  {
    git diff --name-only --diff-filter=ACMR "$base" -- || true
    git diff --name-only --diff-filter=ACMR --cached -- || true
    git diff --name-only --diff-filter=ACMR -- || true
    git ls-files --others --exclude-standard || true
  } | sort -u | while IFS= read -r file; do
    [ -n "$file" ] || continue
    [ -f "$file" ] || continue
    is_test_path "$file" && printf '%s\n' "$file"
  done
}

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
    *.go) command -v go >/dev/null 2>&1 && RUNNER=(go test) ;;
    *.rs) command -v cargo >/dev/null 2>&1 && RUNNER=(cargo test --) ;;
    *.ts | *.tsx | *.js) [ -f "$root/package.json" ] && RUNNER=(npm test --silent --) ;;
  esac
  # An absent runner is a finding for the caller, not a failed command: under
  # `set -e` a falsy last branch would kill the gate before it could say so.
  return 0
}

parse_args() {
  BASE=""
  EXPLICIT_FILES=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --base) shift; BASE="${1:-}"; [ -n "$BASE" ] || usage ;;
      --files) shift; while [ $# -gt 0 ]; do EXPLICIT_FILES+=("$1"); shift; done; break ;;
      -h | --help) usage ;;
      *) usage ;;
    esac
    shift || true
  done
}

# The tests a diff ADDS, by name, for one file. A file-level verdict is not
# enough: a vacuous test hides inside a file whose other tests fail, which is
# exactly how the defect that prompted this gate survived (docs/fail-before.md).
new_pytest_nodes() { # base file
  local base="$1" file="$2" name
  local before after
  before="$(git show "$base:$file" 2>/dev/null | grep -oE '^(async )?def (test_[A-Za-z0-9_]+)' | awk '{print $NF}' | sort -u || true)"
  after="$(grep -oE '^(async )?def (test_[A-Za-z0-9_]+)' "$file" | awk '{print $NF}' | sort -u || true)"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    printf '%s::%s\n' "$file" "$name"
  done < <(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after"))
}

TARGETS=()
RUNNER=()
RUN_OUTPUT=""

# The worktree path is global: the EXIT trap fires after run_against_base has
# returned, where a function-local would be unbound under `set -u`.
WORKTREE=""
cleanup_worktree() {
  [ -n "$WORKTREE" ] && git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  [ -n "$RUN_OUTPUT" ] && rm -f "$RUN_OUTPUT" || true
}

# 125: the base tree could not be checked out. 124 is timeout's own code.
# Copies FILES into a base checkout, runs TARGETS there. The two differ:
# a target can be a pytest node id inside one of the files.
run_against_base() { # base
  local base="$1"
  local file timeout_bin status=0
  WORKTREE="$ROOT/.claude/worktrees/zetetic-fail-before-$$"
  trap cleanup_worktree EXIT
  git worktree add --detach "$WORKTREE" "$base" >/dev/null 2>&1 || return 125
  for file in "${FILES[@]}"; do
    mkdir -p "$WORKTREE/$(dirname "$file")"
    cp "$file" "$WORKTREE/$file"
  done
  timeout_bin="$(command -v timeout || command -v gtimeout || true)"
  RUN_OUTPUT="$(mktemp)"
  set +e
  if [ -n "$timeout_bin" ]; then
    (cd "$WORKTREE" && "$timeout_bin" "$TIMEOUT_SECONDS" "${RUNNER[@]}" "${TARGETS[@]}") >"$RUN_OUTPUT" 2>&1
  else
    (cd "$WORKTREE" && "${RUNNER[@]}" "${TARGETS[@]}") >"$RUN_OUTPUT" 2>&1
  fi
  status=$?
  set -e
  return "$status"
}

collect_files() {
  local base="$1" line
  FILES=()
  if [ ${#EXPLICIT_FILES[@]} -gt 0 ]; then
    FILES=("${EXPLICIT_FILES[@]}")
    return 0
  fi
  while IFS= read -r line; do [ -n "$line" ] && FILES+=("$line"); done < <(changed_test_files "$base")
}

# pytest -rA prints one "PASSED <node>" line per passing test. A node that
# passed on the OLD tree pins nothing the diff introduced.
passed_nodes() {
  [ -f "$RUN_OUTPUT" ] || return 0
  grep -E '^PASSED ' "$RUN_OUTPUT" | awk '{print $2}' | sort -u || true
}

report_vacuous() { # nodes...
  echo "VACUOUS fail-before: new tests that pass against ${BASE:0:12}:"
  printf '  %s\n' "$@"
  echo "  They pin nothing this diff introduced. Make each fail on the old tree first."
  [ "$ZETETIC_PROFILE" = "strict" ] && exit "$EXIT_BLOCKED"
  exit "$EXIT_CLEAN"
}

main() {
  parse_args "$@"
  ROOT="$(repo_root)" || { echo "fail-before: not a git repository" >&2; exit "$EXIT_USAGE"; }
  cd "$ROOT"
  load_profile "$ROOT"
  [ -n "$BASE" ] || BASE="$(resolve_base)"
  if [ -z "$BASE" ]; then
    echo "fail-before: no commit yet; there is no old tree to prove anything against."
    exit "$EXIT_CLEAN"
  fi
  collect_files "$BASE"
  if [ ${#FILES[@]} -eq 0 ]; then
    echo "fail-before: no changed test file against ${BASE:0:12}; nothing to prove."
    exit "$EXIT_CLEAN"
  fi

  local status=0
  detect_runner "$ROOT" "${FILES[0]}"
  if [ ${#RUNNER[@]} -eq 0 ]; then
    echo "INCONCLUSIVE fail-before: no runner detected for ${FILES[0]}; ran nothing."
    exit "$EXIT_CLEAN"
  fi

  local targets=()
  case "${FILES[0]}" in
    *.py)
      local file node
      for file in "${FILES[@]}"; do
        while IFS= read -r node; do [ -n "$node" ] && targets+=("$node"); done \
          < <(new_pytest_nodes "$BASE" "$file")
      done
      if [ ${#targets[@]} -eq 0 ]; then
        echo "fail-before: the diff adds no new test against ${BASE:0:12}; nothing to prove."
        exit "$EXIT_CLEAN"
      fi
      ;;
    *) targets=("${FILES[@]}") ;;
  esac

  TARGETS=("${targets[@]}")
  run_against_base "$BASE" || status=$?
  # 1 is "a test failed", the only code that proves the tests can tell the two
  # trees apart. Everything else means the run did not reach that verdict:
  # pytest returns 5 for "no tests collected", 4 for usage, 127 is a missing
  # command. Reading those as proof is how a gate blesses a run it never made.
  local vacuous=()
  case "${FILES[0]}" in
    *.py) while IFS= read -r node; do [ -n "$node" ] && vacuous+=("$node"); done < <(passed_nodes) ;;
  esac
  case "$status" in
    0) report_vacuous "${vacuous[@]:-${TARGETS[@]}}" ;;
    1)
      [ ${#vacuous[@]} -gt 0 ] && report_vacuous "${vacuous[@]}"
      echo "fail-before: the changed tests fail against ${BASE:0:12}, as they must."
      ;;
    124) echo "INCONCLUSIVE fail-before: the base-tree run exceeded ${TIMEOUT_SECONDS}s." ;;
    125) echo "INCONCLUSIVE fail-before: could not check out ${BASE:0:12}; ran nothing." ;;
    *) echo "INCONCLUSIVE fail-before: the runner exited $status without a test verdict." ;;
  esac
  exit "$EXIT_CLEAN"
}

main "$@"
