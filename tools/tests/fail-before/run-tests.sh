#!/usr/bin/env bash
# Regression tests for plugins/zetetic-gates/tools/fail-before-checker.sh.
# Each case builds a throwaway git repository; nothing here touches the tree.
set -euo pipefail

# (a) a new test that fails on the old code   -> clean, exit 0
# (b) a new test that passes on the old code  -> VACUOUS, exit 0 by default
# (c) the same, under ZETETIC_PROFILE=strict  -> VACUOUS, exit 1
# (d) a vacuous test beside a failing one     -> still named (node granularity)
# (e) a diff that adds no new test            -> nothing to prove, exit 0
# (f) no runner available for the language    -> INCONCLUSIVE, never a pass
# (g) the throwaway worktree is removed afterwards
# (h) a repository with no commit yet          -> nothing to compare, exit 0
# (i) an untracked new test file is seen

cd "$(dirname "$0")"
GATE="$(cd ../../../plugins/zetetic-gates/tools && pwd)/fail-before-checker.sh"
# Same override tests/run-all.sh honours: a python3 that has pytest.
PYTHON="${PYTHON_BIN:-$(command -v python3)}"

PASS=0
FAIL=0

check() { # name expected_code actual_code [grep_pattern] [stdout]
  local name="$1" ec="$2" ac="$3" gp="${4:-}" out="${5:-}" ok=1
  if [[ "$ac" != "$ec" ]]; then ok=0; echo "  FAIL: $name — exit expected $ec got $ac"; fi
  if [[ -n "$gp" ]] && ! grep -q "$gp" <<<"$out"; then
    ok=0
    echo "  FAIL: $name — stdout missing /$gp/"
    echo "    got: $out"
  fi
  if [[ "$ok" == 1 ]]; then echo "  PASS: $name"; PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); fi
}

# One source file and its test committed, then the source changed and the
# given test body appended, uncommitted: the shape of a diff under review.
make_repo() { # dir new_test_body
  local dir="$1" body="$2"
  mkdir -p "$dir/src" "$dir/tests"
  cd "$dir"
  git init -q .
  git config user.email t@t.t
  git config user.name t
  printf 'def answer():\n    return 1\n' > src/thing.py
  printf 'def test_answer_exists():\n    from src.thing import answer\n\n    assert answer()\n' > tests/test_thing.py
  git add -A
  git commit -qm "base"
  printf 'def answer():\n    return 42\n' > src/thing.py
  printf '%s' "$body" >> tests/test_thing.py
  cd - >/dev/null
}

run_gate() { # dir
  (cd "$1" && PATH="$(dirname "$PYTHON"):$PATH" "$GATE" --base HEAD 2>&1)
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$PYTHON" -c "import pytest" 2>/dev/null || {
  echo "SKIP: pytest is not importable by $PYTHON; the gate has no runner to exercise."
  exit 0
}

FAILS_ON_OLD='

def test_answer_is_42():
    from src.thing import answer

    assert answer() == 42
'
PASSES_ON_OLD='

def test_answer_is_truthy():
    from src.thing import answer

    assert answer()
'

make_repo "$WORK/a" "$FAILS_ON_OLD"
out="$(run_gate "$WORK/a")"; code=$?
check "new test that fails on old code" 0 "$code" "as they must" "$out"

make_repo "$WORK/b" "$PASSES_ON_OLD"
out="$(run_gate "$WORK/b")"; code=$?
check "vacuous test, standard profile" 0 "$code" "VACUOUS" "$out"
check "vacuous test names the node" 0 "$code" "test_answer_is_truthy" "$out"

printf 'ZETETIC_PROFILE=strict\n' > "$WORK/b/.zetetic.conf"
set +e
out="$(run_gate "$WORK/b")"; code=$?
set -e
check "vacuous test, strict profile blocks" 1 "$code" "VACUOUS" "$out"

make_repo "$WORK/d" "$FAILS_ON_OLD$PASSES_ON_OLD"
out="$(run_gate "$WORK/d")"; code=$?
check "a failing sibling does not hide a vacuous test" 0 "$code" "VACUOUS" "$out"
check "the vacuous sibling is the one named" 0 "$code" "test_answer_is_truthy" "$out"

make_repo "$WORK/e" ""
out="$(run_gate "$WORK/e")"; code=$?
check "no new test" 0 "$code" "nothing to prove" "$out"

mkdir -p "$WORK/f/tests"
cd "$WORK/f"
git init -q .
git config user.email t@t.t
git config user.name t
printf 'package main\n' > main.go
printf 'package main\n' > tests/a_test.go
git add -A
git commit -qm base
printf 'package main\n// changed\n' > tests/a_test.go
cd - >/dev/null
out="$(cd "$WORK/f" && PATH="/usr/bin:/bin" "$GATE" --base HEAD 2>&1)"; code=$?
check "no runner is inconclusive, not a pass" 0 "$code" "INCONCLUSIVE" "$out"

mkdir -p "$WORK/h"
(cd "$WORK/h" && git init -q . && git config user.email t@t.t && git config user.name t)
out="$(cd "$WORK/h" && PATH="$(dirname "$PYTHON"):$PATH" "$GATE" 2>&1)"; code=$?
check "no commit yet is nothing to compare" 0 "$code" "no commit yet" "$out"

make_repo "$WORK/i" ""
printf 'def test_new_file_is_truthy():\n    from src.thing import answer\n\n    assert answer()\n' > "$WORK/i/tests/test_new.py"
out="$(run_gate "$WORK/i")"; code=$?
check "an untracked test file is seen" 0 "$code" "test_new_file_is_truthy" "$out"

HOOK="$(dirname "$GATE")/../hooks/pre-push-fail-before.sh"
"$PYTHON" test_context.py "$(dirname "$GATE")/../hooks/git-push-context.py"
make_repo "$WORK/setup" '
import pytest
@pytest.fixture
def broken():
    raise RuntimeError("fixture setup")
def test_setup(broken):
    assert True
'
out="$(run_gate "$WORK/setup")"; code=$?
check "fixture error is inconclusive" 0 "$code" "INCONCLUSIVE" "$out"
make_repo "$WORK/skip" '
import pytest
@pytest.mark.skip(reason="no execution")
def test_skipped():
    assert True
'
printf 'ZETETIC_PROFILE=strict\n' > "$WORK/skip/.zetetic.conf"
out="$(run_gate "$WORK/skip")"; code=$?
check "skipped test does not block as vacuous" 0 "$code" "INCONCLUSIVE" "$out"
out="$(cd "$WORK/a" && "$GATE" --base missing-revision 2>&1)"; code=$?
check "invalid base is inconclusive" 0 "$code" "base missing-revision is not a commit" "$out"
printf 'ZETETIC_FAIL_BEFORE_TIMEOUT=invalid\n' > "$WORK/a/.zetetic.conf"
out="$(cd "$WORK/a" && printf '%s' '{"tool_input":{"command":"git push"}}' | "$HOOK" 2>&1)"; code=$?
check "hook emits checker error" 0 "$code" "INCONCLUSIVE" "$out"
check "hook preserves invalid configuration diagnostic" 0 "$code" "must be a whole number" "$out"
out="$(cd "$WORK/a" && printf '%s' '{"tool_input":{"command":"git status"}}' | "$HOOK" 2>&1)"; code=$?
check "hook ignores non-push commands" 0 "$code"
check "non-push hook is quiet" "" "$out"
set +e
out="$(cd "$WORK/b" && printf '%s' '{"tool_input":{"command":"git push"}}' | PATH="$(dirname "$PYTHON"):$PATH" "$HOOK" 2>&1)"; code=$?
set -e
check "hook blocks strict vacuous test" 2 "$code" "BLOCKED" "$out"
make_repo "$WORK/mixed-error" "$FAILS_ON_OLD"'
import pytest
@pytest.fixture
def broken():
    raise RuntimeError("setup")
def test_setup(broken):
    assert True
'
out="$(run_gate "$WORK/mixed-error")"; code=$?
check "a failing test does not hide setup error" 0 "$code" "INCONCLUSIVE" "$out"
make_repo "$WORK/mixed-skip" "$FAILS_ON_OLD"'
import pytest
@pytest.mark.skip(reason="no execution")
def test_skipped():
    assert True
'
out="$(run_gate "$WORK/mixed-skip")"; code=$?
check "a failing test does not hide skipped node" 0 "$code" "INCONCLUSIVE" "$out"
make_repo "$WORK/first-push" "$PASSES_ON_OLD"
(cd "$WORK/first-push" && git update-ref refs/remotes/origin/main HEAD && git add -A && git commit -qm feature)
out="$(cd "$WORK/first-push" && PATH="$(dirname "$PYTHON"):$PATH" "$GATE" 2>&1)"; code=$?
check "first push compares against remote main" 0 "$code" "VACUOUS" "$out"
(cd "$WORK/first-push" && git update-ref -d refs/remotes/origin/main)
out="$(cd "$WORK/first-push" && PATH="$(dirname "$PYTHON"):$PATH" "$GATE" 2>&1)"; code=$?
check "unknown base does not certify committed change" 0 "$code" "INCONCLUSIVE" "$out"

# Repository targeting is part of hook enforcement.
set +e
out="$(cd "$WORK/a" && printf '{"tool_input":{"command":"git push","workdir":"%s"}}' "$WORK/b" | PATH="$(dirname "$PYTHON"):$PATH" "$HOOK" 2>&1)"; code=$?
set -e
check "hook honors event workdir" 2 "$code" "BLOCKED" "$out"
set +e
out="$(cd "$WORK/a" && printf '{"tool_input":{"command":"git -C %s push"}}' "$WORK/b" | PATH="$(dirname "$PYTHON"):$PATH" "$HOOK" 2>&1)"; code=$?
set -e
check "hook honors git -C" 2 "$code" "BLOCKED" "$out"
set +e
out="$(cd "$WORK/a" && printf '{"tool_input":{"command":"cd %s && git push"}}' "$WORK/b" | PATH="$(dirname "$PYTHON"):$PATH" "$HOOK" 2>&1)"; code=$?
set -e
check "hook honors leading cd" 2 "$code" "BLOCKED" "$out"
out="$(cd "$WORK/b" && printf '%s' '{"tool_input":{"command":"echo git push"}}' | "$HOOK" 2>&1)"; code=$?
check "hook ignores command mentions" 0 "$code"
check "command mention is quiet" "" "$out"

# Reporter specimens distinguish executed tests from runner exit codes.
# shellcheck source=plugins/zetetic-gates/tools/fail-before-runners.sh
source "$(dirname "$GATE")/fail-before-runners.sh"
RUN_OUTPUT="$WORK/runner-output"
for specimen in 'go|0|--- PASS: TestAnswer (0.00s)|passed' 'go|1|--- FAIL: TestAnswer (0.00s)|failed' 'go|1|build failed|' 'rs|0|test result: ok. 1 passed; 0 failed;|passed' 'rs|101|test result: FAILED. 0 passed; 1 failed;|failed' 'rs|0|test result: ok. 0 passed; 0 failed;|' 'js|0|# pass 1|passed' 'js|1|# fail 1|failed' 'js|0|# tests 0|' 'js|0|Tests: 1 passed, 1 total|passed' 'ts|1|Tests  1 failed (1)|failed'; do
  IFS='|' read -r ext status summary expected <<<"$specimen"
  FILES=("test.$ext")
  printf '%s\n' "$summary" > "$RUN_OUTPUT"
  actual="$(nonpython_verdict "$status")"
  check "reporter ${FILES[0]}/$status/$summary" "$expected" "$actual"
done

"$PYTHON" test_real_runners.py "$GATE"

leftovers="$(find "$WORK" -type d -name 'zetetic-fail-before-*' | wc -l | tr -d ' ')"
if [[ "$leftovers" == "0" ]]; then
  echo "  PASS: no worktree left behind"; PASS=$((PASS + 1))
else
  echo "  FAIL: $leftovers worktree(s) left behind"; FAIL=$((FAIL + 1))
fi

echo
echo "fail-before: $PASS passed, $FAIL failed"
[[ "$FAIL" == 0 ]]
