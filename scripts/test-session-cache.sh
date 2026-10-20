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

printf "\n%d passed, %d failed\n" "$PASS_COUNT" "$FAIL_COUNT"
[[ "$FAIL_COUNT" -eq 0 ]]
