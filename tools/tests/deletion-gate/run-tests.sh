#!/usr/bin/env bash
# Regression suite for tools/deletion_gate.py + tools/deletion-gate.sh + the
# PreToolUse hook hooks/pre-tool-deletion-gate.py.
#
# Incident: cdeust/cortex-viz commit 45d4a80 deleted three module-level
# forwarders justified as "never had a caller in this repository's history".
# They had four, in files the deletion's own diff never touched. This suite
# proves the gate catches that SHAPE offline (a synthetic fixture — the real
# commit is verified once, manually, against the network, and that raw output
# is what the PR body carries; a CI regression suite must not depend on an
# external clone succeeding). Every fixture is a throwaway git repo built and
# torn down under $TMP; nothing here touches the real tree.
#
# Cases (mirrors the task's acceptance criteria):
#   1. incident shape: removed forwarder, live caller in an untouched file -> BLOCK, names it
#   2. legitimate deletion, substantive Retired-Because trailer          -> PASS
#   3. no survivors, no trailer at all                                   -> BLOCK
#   4. no survivors, trailer is observation-only ("no callers")          -> BLOCK
#   5. rename + move (same body, new name, new file), no trailer needed  -> PASS
#   6. test-path removal is exempt                                      -> PASS (SKIP)
#   7. --staged with no message file: survivors still block, but a
#      legitimate no-survivor removal is deferred, not blocked           -> BLOCK / PASS
#   8. the shell wrapper delegates argv/exit code identically to the .py
#   9. the PreToolUse hook blocks an Edit that would strand a real caller,
#      and passes a rename in-place with no other caller left dangling
set -uo pipefail

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SUITE_DIR/../../.." && pwd)"
GATE_PY="$REPO/tools/deletion_gate.py"
GATE_SH="$REPO/tools/deletion-gate.sh"
HOOK="$REPO/hooks/pre-tool-deletion-gate.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }
check_exit() { # name expected_code actual_code
  [[ "$3" == "$2" ]] && ok "$1" || { bad "$1 (expected exit $2, got $3)"; }
}
check_grep() { # name pattern haystack
  grep -qF "$2" <<<"$3" && ok "$1" || { bad "$1 (missing: $2)"; }
}

git_repo() { # name -> sets REPO_PATH, cd's into it, inits with committer identity
  REPO_PATH="$TMP/$1"
  mkdir -p "$REPO_PATH"
  (cd "$REPO_PATH" && git init -q && git config user.email t@t.dev && git config user.name t)
}

echo "deletion-gate regression tests"

# --- 1. incident shape: a caller in a file the diff never touches ----------
git_repo incident
(
  cd "$REPO_PATH" || exit 1
  mkdir -p pkg
  cat > pkg/stream.py <<'EOF'
def emit(stage, payload):
    return (stage, payload)
EOF
  cat > pkg/build_run.py <<'EOF'
from pkg.stream import emit

def run():
    return emit("build", {})
EOF
  git add -A && git commit -qm init
  printf '' > pkg/stream.py
  git add -A
  git commit -qm "$(printf 'refactor: drop dead forwarder\n\nemit had never had a caller in this repository history.')"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "incident shape blocks" 1 "$RC"
check_grep "incident shape names the surviving caller" "pkg/build_run.py" "$OUT"

# --- 2. legitimate deletion, substantive trailer ----------------------------
git_repo legit-trailer
(
  cd "$REPO_PATH" || exit 1
  printf 'def legacy_export(x):\n    return x * 2\n' > lib.py
  git add -A && git commit -qm init
  printf '' > lib.py
  git add -A
  git commit -qm "$(printf 'refactor: drop legacy_export\n\nRetired-Because: superseded by the streaming exporter in export_v2.py two releases ago; no remaining call path in this repo or its documented integrations.')"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "substantive trailer passes" 0 "$RC"

# --- 3. no survivors, no trailer at all -------------------------------------
git_repo no-trailer
(
  cd "$REPO_PATH" || exit 1
  printf 'def orphan(x):\n    return x\n' > lib.py
  git add -A && git commit -qm init
  printf '' > lib.py
  git add -A && git commit -qm "chore: drop orphan"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "no trailer at all blocks" 1 "$RC"
check_grep "no-trailer message names the missing key" "Retired-Because" "$OUT"

# --- 4. observation-only trailer --------------------------------------------
git_repo observation-only
(
  cd "$REPO_PATH" || exit 1
  printf 'def orphan(x):\n    return x\n' > lib.py
  git add -A && git commit -qm init
  printf '' > lib.py
  git add -A
  git commit -qm "$(printf 'chore: drop orphan\n\nRetired-Because: no callers, unused, dead code.')"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "observation-only trailer blocks" 1 "$RC"
check_grep "observation-only message names the defect" "restates the absence" "$OUT"

# --- 5. rename + move, same body, no trailer --------------------------------
git_repo rename-move
(
  cd "$REPO_PATH" || exit 1
  mkdir -p server
  cat > server/graph_event_stream.py <<'EOF'
def emit(stage, nodes, edges, chunk=1000):
    payload = _slim(nodes, edges)
    _buffer.append((stage, payload, chunk))
    return payload
EOF
  git add -A && git commit -qm init
  git mv server/graph_event_stream.py server/graph_stream_api.py
  python3 -c "
p = 'server/graph_stream_api.py'
text = open(p).read().replace('def emit(', 'def publish(')
open(p, 'w').write(text)
"
  git add -A
  git commit -qm "refactor: rename emit -> publish, module renamed"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "rename+move passes with no trailer" 0 "$RC"
check_grep "rename+move names the match" "rename/move" "$OUT"

# --- 5b. near-miss: substantially different body is NOT a rename match -----
# Guards the low side of RENAME_SIMILARITY_THRESHOLD: two unrelated functions
# must never be waved through as "the same thing, renamed" just because one
# was removed and another was added in the same commit.
git_repo near-miss
(
  cd "$REPO_PATH" || exit 1
  cat > lib.py <<'EOF'
def emit(stage, nodes, edges, chunk=1000):
    payload = _slim(nodes, edges)
    _buffer.append((stage, payload, chunk))
    return payload
EOF
  git add -A && git commit -qm init
  cat > lib.py <<'EOF'
def unrelated_new_feature(a, b, c):
    total = 0
    for item in (a, b, c):
        if item is None:
            continue
        total += len(str(item))
    return total * 2 - 1
EOF
  git add -A && git commit -qm "chore: drop emit, add an unrelated feature"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "a substantially different added function is not a rename match" 1 "$RC"
[[ "$OUT" != *"rename/move"* ]] && ok "near-miss is not reported as a rename" \
  || bad "near-miss was incorrectly treated as a rename"

# --- 5c. shell function removal: brace-family body extraction --------------
git_repo shell-removal
(
  cd "$REPO_PATH" || exit 1
  cat > lib.sh <<'EOF'
emit_event() {
  echo "$1"
}
EOF
  cat > caller.sh <<'EOF'
#!/usr/bin/env bash
source ./lib.sh
emit_event "hello"
EOF
  git add -A && git commit -qm init
  printf '#!/usr/bin/env bash\n' > lib.sh
  git add -A && git commit -qm "chore: drop emit_event, no trailer"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "shell function removal with a surviving caller blocks" 1 "$RC"
check_grep "shell removal names the surviving caller" "caller.sh" "$OUT"

# --- 5d. rename-match boundary: ratio == threshold is a match (>=, not >) --
# Unit-level, not an E2E git fixture: constructing two real function bodies
# whose difflib ratio lands on EXACTLY 0.90 (not near it) needs precise
# control over the compared strings, which the git-diff pipeline does not
# give byte-for-byte. 'AAAAAAAAAB' vs 'AAAAAAAAAC' is a verified case (9
# matching chars / 20 total = 0.90 exactly, in Python float equality).
BOUNDARY_OUT="$(python3 -c "
import sys; sys.path.insert(0, '$REPO/tools')
import deletion_gate as dg
removed = dg.Definition('a.py', 'probe_a', 'function', 'AAAAAAAAAB', 'python')
added = dg.Definition('b.py', 'probe_b', 'function', 'AAAAAAAAAC', 'python')
import difflib
ratio = difflib.SequenceMatcher(None, dg.normalize_body(removed.body, removed.name), dg.normalize_body(added.body, added.name)).ratio()
assert ratio == dg.RENAME_SIMILARITY_THRESHOLD, f'fixture does not sit on the boundary: {ratio}'
match = dg.find_rename_match(removed, [added], set())
print('MATCH' if match else 'NO_MATCH')
")"
[[ "$BOUNDARY_OUT" == "MATCH" ]] \
  && ok "rename match at the exact threshold is accepted (>=, not >)" \
  || bad "rename match at the exact threshold is accepted (>=, not >) (got: $BOUNDARY_OUT)"

# --- 5e. shell removal of the SECOND definition in a file ------------------
# Exercises _brace_block_end's own closing '}': a defect there over-extends
# the FIRST function's body to end-of-file, which silently swallows every
# definition that follows it and drops them from extraction entirely — the
# removed def would never even enter the removed-set, a false PASS with no
# trace. Order matters here (helper first, emit_event second) precisely
# because that is the shape a boundary defect hides.
git_repo shell-second-def
(
  cd "$REPO_PATH" || exit 1
  cat > lib.sh <<'EOF'
helper() {
  echo "helper"
}

emit_event() {
  echo "$1"
}
EOF
  cat > caller.sh <<'EOF'
#!/usr/bin/env bash
source ./lib.sh
emit_event "hello"
EOF
  git add -A && git commit -qm init
  cat > lib.sh <<'EOF'
helper() {
  echo "helper"
}
EOF
  git add -A && git commit -qm "chore: drop emit_event (second def in file), no trailer"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "removing the second shell def in a file still blocks" 1 "$RC"
check_grep "second-def removal names the surviving caller" "caller.sh" "$OUT"

# --- 6. test-path exemption -------------------------------------------------
git_repo test-exempt
(
  cd "$REPO_PATH" || exit 1
  mkdir -p tests
  printf 'def test_something():\n    assert True\n' > tests/test_thing.py
  git add -A && git commit -qm init
  printf '' > tests/test_thing.py
  git add -A && git commit -qm "chore: drop a retired test, no trailer"
)
HEAD="$(cd "$REPO_PATH" && git rev-parse HEAD)"
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --commit "$HEAD" 2>&1)"; RC=$?
check_exit "test-path removal is exempt" 0 "$RC"
check_grep "test-path removal is reported as SKIP" "SKIP" "$OUT"

# --- 7. --staged: survivors still block; no-survivor removal is deferred ---
git_repo staged-net
(
  cd "$REPO_PATH" || exit 1
  cat > lib.py <<'EOF'
def emit(x):
    return x
def orphan(x):
    return x
EOF
  cat > caller.py <<'EOF'
from lib import emit
def run():
    return emit(1)
EOF
  git add -A && git commit -qm init
  python3 -c "
p='lib.py'
open(p,'w').write('')
"
  git add -A
)
OUT="$(python3 "$GATE_PY" --repo "$REPO_PATH" --staged 2>&1)"; RC=$?
check_exit "staged net still blocks a real survivor" 1 "$RC"
check_grep "staged net names the caller" "caller.py" "$OUT"
check_grep "staged net defers the no-survivor removal (not a false block)" \
  "required at commit time" "$OUT"

# --- 8. shell wrapper parity ------------------------------------------------
SH_OUT="$(bash "$GATE_SH" --repo "$REPO_PATH" --staged 2>&1)"; SH_RC=$?
check_exit "shell wrapper mirrors the python exit code" "$RC" "$SH_RC"
[[ "$SH_OUT" == "$OUT" ]] && ok "shell wrapper mirrors stdout" || bad "shell wrapper output diverged"

# --- 9. PreToolUse hook: Edit-time blocking on a live caller, rename passes -
git_repo hook-repo
(
  cd "$REPO_PATH" || exit 1
  cat > lib.py <<'EOF'
def emit(x):
    return x + 1
EOF
  cat > caller.py <<'EOF'
from lib import emit

def run():
    return emit(3)
EOF
  git add -A && git commit -qm init
)
HOOK_BLOCK_JSON=$(python3 -c "
import json
print(json.dumps({'tool_name':'Edit','tool_input':{
  'file_path': '$REPO_PATH/lib.py',
  'old_string': 'def emit(x):\n    return x + 1\n',
  'new_string': ''}}))
")
HOOK_OUT="$(printf '%s' "$HOOK_BLOCK_JSON" | python3 "$HOOK" 2>&1)"; HOOK_RC=$?
check_exit "hook blocks removal of a live caller" 2 "$HOOK_RC"
check_grep "hook names the surviving caller" "caller.py" "$HOOK_OUT"

HOOK_PASS_JSON=$(python3 -c "
import json
print(json.dumps({'tool_name':'Edit','tool_input':{
  'file_path': '$REPO_PATH/caller.py',
  'old_string': 'def run():\n    return emit(3)\n',
  'new_string': 'def run():\n    return 3\n'}}))
")
printf '%s' "$HOOK_PASS_JSON" | python3 "$HOOK" >/dev/null 2>&1; HOOK_RC2=$?
check_exit "hook allows an edit that removes no definition" 0 "$HOOK_RC2"

echo ""
echo "deletion-gate: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
