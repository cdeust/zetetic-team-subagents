#!/usr/bin/env bash
# test-session-cache.sh — Regression test: tools/session-store.sh must keep its
# cache under the user's Claude config dir, never inside the working repository.
#
# An untracked .claude/session-cache.json in the repo blocked every worktree
# cleanup (a worktree manager refuses to delete a worktree with untracked files).
#
# Tests:
#   C1  `save` in a git repo leaves `git status --porcelain` empty.
#   C2  `load` prints the saved context.
#   C3  Two different repos get different cache files under the config dir.
#   C4  The cache file is under $CLAUDE_CONFIG_DIR/session-cache/.
#   C5  `load` from a subdirectory finds the repo's cache.
#   C6  A linked worktree gets its own cache and stays clean.
#   C7  With only shasum on PATH, the key matches sha256(toplevel)[0:16].
#   C8  With neither sha256sum nor shasum, the python3 fallback gives the same key.
#
# HOME and CLAUDE_CONFIG_DIR point at a throwaway dir; the real ~/.claude is
# never touched.

set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
STORE="$REPO/tools/session-store.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; (( PASS_COUNT++ )) || true; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; (( FAIL_COUNT++ )) || true; }

export HOME="$TMP/home"
export CLAUDE_CONFIG_DIR="$TMP/home/.claude"
mkdir -p "$HOME"

mkrepo() {
  git init -q "$1"
  git -C "$1" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
}
mkrepo "$TMP/repoA"
mkrepo "$TMP/repoB"

(cd "$TMP/repoA" && bash "$STORE" save "context-A" >/dev/null)
(cd "$TMP/repoB" && bash "$STORE" save "context-B" >/dev/null)

# C1
if [[ -z "$(git -C "$TMP/repoA" status --porcelain)" ]]; then
  pass "C1 save leaves the repo clean"
else
  fail "C1 save dirtied the repo: $(git -C "$TMP/repoA" status --porcelain)"
fi

# C2
if (cd "$TMP/repoA" && bash "$STORE" load) | grep -q "context-A"; then
  pass "C2 load prints the saved context"
else
  fail "C2 load did not print the saved context"
fi

# C3
files="$(find "$CLAUDE_CONFIG_DIR/session-cache" -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ' || true)"
if [[ "$files" == "2" ]] && ! (cd "$TMP/repoB" && bash "$STORE" load) | grep -q "context-A"; then
  pass "C3 two repos get two different cache files"
else
  fail "C3 expected 2 distinct cache files, found $files"
fi

# C4
if [[ -d "$CLAUDE_CONFIG_DIR/session-cache" ]] && [[ -z "$(find "$CLAUDE_CONFIG_DIR" -type f -not -path "$CLAUDE_CONFIG_DIR/session-cache/*")" ]]; then
  pass "C4 cache lives under CLAUDE_CONFIG_DIR/session-cache/"
else
  fail "C4 stray files outside session-cache/"
fi

# C5
mkdir -p "$TMP/repoA/sub/dir"
if (cd "$TMP/repoA/sub/dir" && bash "$STORE" load) | grep -q "context-A"; then
  pass "C5 load from a subdirectory finds the repo's cache"
else
  fail "C5 load from a subdirectory missed the repo's cache"
fi

# C6
WT="$TMP/repoA/.claude/worktrees/wtA"
git -C "$TMP/repoA" worktree add -q "$WT" -b wt-branch
(cd "$WT" && bash "$STORE" save "context-WT" >/dev/null)
if [[ -z "$(git -C "$WT" status --porcelain)" ]] \
   && (cd "$WT" && bash "$STORE" load) | grep -q "context-WT" \
   && (cd "$TMP/repoA" && bash "$STORE" load) | grep -q "context-A"; then
  pass "C6 a worktree gets its own cache and stays clean"
else
  fail "C6 worktree cache collided with the main checkout or dirtied it"
fi

# C7, C8: a PATH holding only the commands session-store.sh needs.
expected_key() {
  printf '%s' "$1" | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:16])'
}
mkbin() {
  mkdir -p "$1"
  local c
  for c in bash git cut mkdir cat date python3 dirname; do
    ln -sf "$(command -v "$c")" "$1/$c"
  done
}
ROOT_A="$(cd "$TMP/repoA" && git rev-parse --show-toplevel)"
KEY_A="$(expected_key "$ROOT_A")"

mkbin "$TMP/bin-shasum"
if command -v shasum >/dev/null 2>&1; then
  ln -sf "$(command -v shasum)" "$TMP/bin-shasum/shasum"
  rm -f "$CLAUDE_CONFIG_DIR/session-cache/$KEY_A.json"
  (cd "$TMP/repoA" && PATH="$TMP/bin-shasum" bash "$STORE" save "context-S" >/dev/null 2>&1) || true
  if [[ -f "$CLAUDE_CONFIG_DIR/session-cache/$KEY_A.json" ]]; then
    pass "C7 shasum-only path gives the sha256 key"
  else
    fail "C7 shasum-only path did not write $KEY_A.json"
  fi
else
  fail "C7 shasum not installed on this host"
fi

mkbin "$TMP/bin-nohash"
rm -f "$CLAUDE_CONFIG_DIR/session-cache/$KEY_A.json"
(cd "$TMP/repoA" && PATH="$TMP/bin-nohash" bash "$STORE" save "context-P" >/dev/null 2>&1) || true
if [[ -f "$CLAUDE_CONFIG_DIR/session-cache/$KEY_A.json" ]] \
   && (cd "$TMP/repoA" && PATH="$TMP/bin-nohash" bash "$STORE" load) | grep -q "context-P"; then
  pass "C8 no hash tool: python3 fallback gives the same key"
else
  fail "C8 no hash tool: save/load failed"
fi

printf "\n%d passed, %d failed\n" "$PASS_COUNT" "$FAIL_COUNT"
[[ "$FAIL_COUNT" -eq 0 ]]
