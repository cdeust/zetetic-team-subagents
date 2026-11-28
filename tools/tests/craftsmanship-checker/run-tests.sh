#!/usr/bin/env bash
# Regression suite — tools/craftsmanship-checker.sh.
#
# Asserts:
#   C1 diff scoping (CRAFT-STAGED-PREEXISTING). --staged reports a finding only
#      when its span intersects a line the commit changed. A commit that
#      rewords one doc comment in a file holding a pre-existing over-long
#      function was refused over that function — code the commit did not touch
#      and could not fix in the same commit. Whole-file MEASUREMENT is kept;
#      only the blame narrows. Boundary cases, each asserted:
#        - pre-existing long function, untouched      -> allowed
#        - the same function, one line inside edited  -> blocked
#        - a newly added long function                -> blocked
#        - FILE_TOO_LONG (no span)                    -> attributed whenever the
#          file changed at all; see craft_d1_file_too_long for why
#        - --files / --full audit                     -> unchanged, whole-file
#      ZETETIC_DIFF_RANGES is the contract (tools/lib/diff-scope.sh): the commit
#      gate (hooks/lib/staged_checks.py) checks frozen index blobs in a
#      disposable repository, so it supplies the ranges rather than letting the
#      checker derive them from a `git diff --cached` that compares nothing.

set -uo pipefail

# Both resolved before any `cd`: the suite changes directory, after which a
# path derived from a relative $0 no longer resolves.
SUITE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$(cd "$SUITE_DIR/../.." && pwd)/craftsmanship-checker.sh"
FIXTURES="$SUITE_DIR/fixtures"
PASS=0; FAIL=0

run_case() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS: $name"; PASS=$((PASS+1)); else echo "FAIL: $name"; FAIL=$((FAIL+1)); fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || { echo "FAIL: could not cd to temp dir" >&2; exit 1; }

# A rust function of $1 trivial body lines, named $2, preceded by a doc comment.
long_fn() {
  local n="$1" name="$2" i
  echo "/// doc line for $name"
  echo "pub fn $name(x: u32) -> u32 {"
  for ((i = 1; i <= n; i++)); do echo "    let v$i = $i;"; done
  echo "    x"
  echo "}"
}

# ── C1 diff scoping ────────────────────────────────────────────────────
mkdir -p scope/app/src
( cd scope && git init -q . && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
long_fn 60 handle > scope/app/src/api.rs
( cd scope && git add -A && git commit -qm base ) >/dev/null 2>&1

# The reported case: reword the doc comment on line 1 only.
sed -e '1s|.*|/// doc line for handle, reworded|' scope/app/src/api.rs > scope/tmp.rs
mv scope/tmp.rs scope/app/src/api.rs
( cd scope && git add -A ) >/dev/null 2>&1
out=$(cd scope && FUNC_MAX=50 "$CHECKER" --staged 2>&1); rc=$?
run_case "C1 doc-comment-only change: the untouched long function is not reported" \
  test "$(grep -c FUNCTION_TOO_LONG <<<"$out")" -eq 0
run_case "C1 doc-comment-only change: the commit is allowed (exit 0)" test "$rc" -eq 0
run_case "C1 the measured-but-unattributed finding is reported, not hidden" \
  grep -q "Pre-existing: 1 finding" <<<"$out"

# The same function, one line INSIDE it edited: the commit touched it, so it blocks.
sed -e '30s|.*|    let v28 = 999;|' scope/app/src/api.rs > scope/tmp.rs
mv scope/tmp.rs scope/app/src/api.rs
( cd scope && git add -A ) >/dev/null 2>&1
out=$(cd scope && FUNC_MAX=50 "$CHECKER" --staged 2>&1); rc=$?
run_case "C1 a line edited inside the long function: reported" \
  grep -q FUNCTION_TOO_LONG <<<"$out"
run_case "C1 a line edited inside the long function: blocks (exit 1)" test "$rc" -eq 1

# A newly added long function blocks, and the untouched one still does not.
long_fn 70 fresh >> scope/app/src/api.rs
( cd scope && git checkout -q -- app/src/api.rs 2>/dev/null; git add -A ) >/dev/null 2>&1
long_fn 60 handle > scope/app/src/api.rs
long_fn 70 fresh >> scope/app/src/api.rs
( cd scope && git add -A ) >/dev/null 2>&1
out=$(cd scope && FUNC_MAX=50 "$CHECKER" --staged 2>&1)
run_case "C1 a newly added long function is reported" grep -q "fresh\|FUNCTION_TOO_LONG" <<<"$out"
run_case "C1 exactly one function is reported (the added one, not the untouched one)" \
  test "$(grep -c FUNCTION_TOO_LONG <<<"$out")" -eq 1

# --files audit is unchanged: it reports both.
out=$(cd scope && FUNC_MAX=50 "$CHECKER" --files app/src/api.rs 2>&1)
run_case "C1 --files audit still reports both functions (whole-file, unscoped)" \
  test "$(grep -c FUNCTION_TOO_LONG <<<"$out")" -eq 2

# FILE_TOO_LONG has no span: it is attributed whenever the file changed at all.
out=$(cd scope && FILE_MAX=10 FUNC_MAX=5000 SIZE_FLEX_BAND=1.0 "$CHECKER" --staged 2>&1)
run_case "C1 FILE_TOO_LONG (no span) is attributed to a commit that changed the file" \
  grep -q FILE_TOO_LONG <<<"$out"

# A caller-supplied range scopes --files too: this is the commit-gate path,
# where the checker runs on frozen blobs in a repository with no usable diff.
out=$(cd scope && ZETETIC_DIFF_RANGES="app/src/api.rs:1-1" FUNC_MAX=50 \
      "$CHECKER" --files app/src/api.rs 2>&1)
run_case "C1 a caller-supplied range scopes --files (the commit-gate path)" \
  test "$(grep -c FUNCTION_TOO_LONG <<<"$out")" -eq 0

# C5 FALSE NEGATIVES. Diff scoping can only ever hide a finding, so every bug in
# it is a MISSED violation -- the dangerous direction for a gate. These three
# were found by adversarial review and each is a real miss, not a theory.

# C5a path collision. ds_ranges_for matched a path SUFFIX, so with both `a/x.rs`
# and `z/a/x.rs` staged, `z/a/x.rs` ends with `/a/x.rs` and inherited the other
# file's ranges -- its own violation was suppressed. Only exact matches count
# now, with ZETETIC_DIFF_ROOT resolving an absolute path to the recorded form.
# `a/x.rs` is short and clean so it can contribute no finding of its own; the
# only finding available is z/a/x.rs's long function, edited at line 5. git lists
# `a/x.rs` first, so pre-fix z/a/x.rs took its far-away range and reported 0.
mkdir -p collide/a collide/z/a
( cd collide && git init -q . && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
long_fn 80 inner > collide/z/a/x.rs
printf 'fn tiny() -> u32 {\n    1\n}\n' > collide/a/x.rs
for i in $(seq 1 200); do echo "// pad $i" >> collide/a/x.rs; done
( cd collide && git add -A && git commit -qm base ) >/dev/null 2>&1
sed -e '5s|.*|    let v4 = 999;|' collide/z/a/x.rs > collide/t && mv collide/t collide/z/a/x.rs
sed -e '150s|.*|// pad 147 reworded|' collide/a/x.rs > collide/t && mv collide/t collide/a/x.rs
( cd collide && git add -A ) >/dev/null 2>&1
run_case "C5a a path that ends with another staged path keeps its own ranges" \
  test "$(cd collide && FUNC_MAX=50 SIZE_FLEX_BAND=1.0 FILE_MAX=5000 "$CHECKER" --staged 2>&1 \
          | grep -c FUNCTION_TOO_LONG)" -eq 1

# C5b a deletion-only commit. A `+n,0` hunk records no ADDED line, yet deleting
# a `def`/`fn` line merges two functions into one over-long one. The deletion
# SITE is now recorded as a point range, so that span is attributed.
mkdir -p del && ( cd del && git init -q . && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
{ echo "def a():"; for i in $(seq 1 40); do echo "    x$i = $i"; done
  echo "def b():"; for i in $(seq 1 40); do echo "    y$i = $i"; done; } > del/p.py
( cd del && git add -A && git commit -qm base ) >/dev/null 2>&1
grep -v '^def b():' del/p.py > del/t && mv del/t del/p.py
( cd del && git add -A ) >/dev/null 2>&1
run_case "C5b a deletion that merges two functions into an over-long one: blocked" \
  test "$(cd del && FUNC_MAX=50 SIZE_FLEX_BAND=1.0 "$CHECKER" --staged 2>&1 \
          | grep -c FUNCTION_TOO_LONG)" -eq 1

# C5c spoofed diff header. The range parser read `+++ b/` lines out of a combined
# diff, so an ADDED CONTENT line reading `++ b/ignored` opened a bogus record and
# the real file's later hunks were credited to it. The file list now comes from
# --name-only -z, which file content cannot spoof.
mkdir -p spoof && ( cd spoof && git init -q . && git config user.email t@t && git config user.name t ) >/dev/null 2>&1
{ echo "// header"; echo "function big(a) {"
  for i in $(seq 1 80); do echo "    var v$i = $i;"; done
  echo "    return a;"; echo "}"; } > spoof/m.js
( cd spoof && git add -A && git commit -qm base ) >/dev/null 2>&1
{ echo "++ b/ignored"; tail -n +2 spoof/m.js; } > spoof/t && mv spoof/t spoof/m.js
sed -e '70s|.*|    var v69 = 999;|' spoof/m.js > spoof/t && mv spoof/t spoof/m.js
( cd spoof && git add -A ) >/dev/null 2>&1
run_case "C5c an added line that looks like a diff header cannot hide a finding" \
  test "$(cd spoof && FUNC_MAX=50 SIZE_FLEX_BAND=1.0 "$CHECKER" --staged 2>&1 \
          | grep -c FUNCTION_TOO_LONG)" -eq 1

echo "----------------------------------------"
echo "craftsmanship-checker suite: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
