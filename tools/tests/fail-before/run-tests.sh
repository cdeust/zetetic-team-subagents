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

leftovers="$(find "$WORK" -type d -name 'zetetic-fail-before-*' | wc -l | tr -d ' ')"
if [[ "$leftovers" == "0" ]]; then
  echo "  PASS: no worktree left behind"; PASS=$((PASS + 1))
else
  echo "  FAIL: $leftovers worktree(s) left behind"; FAIL=$((FAIL + 1))
fi

echo
echo "fail-before: $PASS passed, $FAIL failed"
[[ "$FAIL" == 0 ]]
