#!/usr/bin/env bash
# test-worktree-sweep-safety.sh — Regression test for issue #33: sweep must
# never remove a freshly-created worktree, and must still remove genuinely
# stale merged ones.
#
# Root cause (issue #33): `git merge-base --is-ancestor <branch>
# origin/main` returns TRUE for a brand-new branch with zero commits (its
# tip equals origin/main's tip). Combined with a clean working tree (true
# before the agent's first edit), the old sweep logic classified an
# untouched, minutes-old worktree as "merged + clean" and removed it.
#
# Tests:
#   P1  Fresh worktree (0 commits, clean, /tmp path) survives a sweep run
#       within the grace period — proves the fix closes the race.
#   P2  A worktree older than the grace period, still merged + clean, IS
#       removed and deregistered — proves the fix does not disable cleanup.
#   P3  A worktree outside /tmp and .claude/worktrees (deliberate location) is never touched
#       regardless of age or merge state.
#   P4  A squash-merged (tip NOT an ancestor of origin/main) clean tmp
#       worktree is removed and its branch deleted — the shape every
#       anthropic-partnership repo produces, which the ancestor test alone
#       never matched (2026-09-10: 30 merged worktrees left standing).
#   P5  A tmp worktree carrying an unmerged commit is kept, branch included.
#   P6  A squash-merged clean worktree under <repo>/.claude/worktrees is
#       removed (the owner's sanctioned worktree location since 2026-09-08).
#   P7  An unmerged worktree under <repo>/.claude/worktrees is kept.
#
# Invariants tested:
#   - Directory + `git worktree list` registration both survive P1.
#   - Directory + `git worktree list` registration both gone after P2.
#   - P3's worktree is untouched in both directory and registration.

set -euo pipefail

REPO="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
MANAGER="$REPO/tools/worktree-manager.sh"

TMP="$(mktemp -d)"
# A second scratch root guaranteed OUTSIDE /tmp and /private/tmp, for P3.
# `mktemp -d`'s default TMPDIR is platform-dependent (/tmp on Linux CI
# runners, but $TMPDIR under /var/folders on macOS) — using it directly for
# a "deliberate, non-tmp" fixture is not portable. Root it under $HOME
# instead, which is never under /tmp on either platform.
NONTMP_ROOT="$(mktemp -d "${HOME}/.zts-sweep-test-XXXXXX")"
TARGET=""
cleanup() {
  if [[ -n "$TARGET" ]]; then
    git -C "$TARGET" worktree list --porcelain 2>/dev/null \
      | awk '/^worktree/ {print $2}' | grep -v "^$TARGET\$" \
      | xargs -I{} git -C "$TARGET" worktree remove --force {} 2>/dev/null || true
  fi
  rm -rf "$TMP" "$NONTMP_ROOT"
}
trap cleanup EXIT

PASS_COUNT=0
FAIL_COUNT=0
pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; (( PASS_COUNT++ )) || true; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; (( FAIL_COUNT++ )) || true; }

# Throwaway target repo with an `origin/main` remote-tracking ref, since
# sweep_worktrees requires origin/main to exist locally.
TARGET="$TMP/target"
mkdir -p "$TARGET"
git -C "$TARGET" init -q -b main
# Local-only identity: CI runners carry no global git user.name/user.email,
# and this repo must not depend on one existing.
git -C "$TARGET" config user.email "test@example.invalid"
git -C "$TARGET" config user.name "Worktree Sweep Test"
git -C "$TARGET" commit -q --allow-empty -m init
git -C "$TARGET" update-ref refs/remotes/origin/main refs/heads/main
git -C "$TARGET" remote add origin "$TARGET" 2>/dev/null || true

AUDIT_LOG="$TMP/audit.log"

# ── P1: fresh worktree survives within grace period ─────────────────────────
echo "P1: fresh worktree (0 commits, clean) survives a sweep within grace period"
FRESH="/tmp/zts-sweep-test-fresh-$$"
rm -rf "$FRESH"
git -C "$TARGET" worktree add -q "$FRESH" -b test/fresh origin/main
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=3600 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ -d "$FRESH" ]]; then pass "directory still present"; else fail "directory removed"; fi
if git -C "$TARGET" worktree list | grep -q "$FRESH"; then
  pass "still registered in git worktree list"
else
  fail "deregistered from git worktree list"
fi
git -C "$TARGET" worktree remove --force "$FRESH" 2>/dev/null || true
git -C "$TARGET" branch -D test/fresh 2>/dev/null || true

# ── P2: stale merged worktree IS removed (grace period elapsed) ─────────────
echo "P2: stale merged+clean worktree is removed once past grace period"
STALE="/tmp/zts-sweep-test-stale-$$"
rm -rf "$STALE"
git -C "$TARGET" worktree add -q "$STALE" -b test/stale origin/main
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ ! -d "$STALE" ]]; then pass "directory removed"; else fail "directory still present"; rm -rf "$STALE"; fi
if git -C "$TARGET" worktree list | grep -q "$STALE"; then
  fail "still registered in git worktree list"
else
  pass "deregistered from git worktree list"
fi

# ── P3: non-tmp worktree is never touched ────────────────────────────────────
echo "P3: worktree outside /tmp is never removed regardless of age/merge state"
DELIBERATE="$NONTMP_ROOT/deliberate-wt"
git -C "$TARGET" worktree add -q "$DELIBERATE" -b test/deliberate origin/main
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ -d "$DELIBERATE" ]]; then pass "directory still present"; else fail "directory removed"; fi
if git -C "$TARGET" worktree list | grep -q "$DELIBERATE"; then
  pass "still registered in git worktree list"
else
  fail "deregistered from git worktree list"
fi
git -C "$TARGET" worktree remove --force "$DELIBERATE" 2>/dev/null || true
git -C "$TARGET" branch -D test/deliberate 2>/dev/null || true

# Helper for P4-P7: one commit on <branch> in <worktree>, so the branch is no
# longer an ancestor of origin/main.
commit_on() {
  local wt="$1" name="$2"
  echo "$name" > "$wt/$name.txt"
  git -C "$wt" add "$name.txt"
  git -C "$wt" -c user.email=test@example.invalid -c user.name="Worktree Sweep Test" \
    commit -q -m "$name"
}
# Squash-merges <branch> into main and moves origin/main forward, the way a
# GitHub squash merge leaves the repository (no merge commit, tip not an ancestor).
squash_into_main() {
  local branch="$1"
  git -C "$TARGET" merge --squash -q "$branch"
  git -C "$TARGET" commit -q -m "squash: $branch"
  git -C "$TARGET" update-ref refs/remotes/origin/main refs/heads/main
}

# ── P8: inventory names the verdict sweep will apply ─────────────────────────
echo "P8: inventory reports keep:deliberate-path for a worktree outside the sweepable roots"
INV="$NONTMP_ROOT/inventory-wt"
git -C "$TARGET" worktree add -q "$INV" -b test/inventory origin/main
# Captured first: `grep -q` closing the pipe early would turn the manager's
# SIGPIPE into a pipefail failure and mask a correct report.
INV_OUT="$("$MANAGER" inventory "$TARGET" 2>/dev/null || true)"
if grep -q "keep:deliberate-path .* test/inventory " <<<"$INV_OUT"; then
  pass "inventory lists the deliberate worktree with its verdict"
else
  fail "inventory verdict missing"
fi
git -C "$TARGET" worktree remove --force "$INV" 2>/dev/null || true
git -C "$TARGET" branch -D test/inventory 2>/dev/null || true

# ── P4: squash-merged tmp worktree is removed ────────────────────────────────
echo "P4: squash-merged (non-ancestor) clean tmp worktree is removed and its branch deleted"
SQUASHED="/tmp/zts-sweep-test-squashed-$$"
rm -rf "$SQUASHED"
git -C "$TARGET" worktree add -q "$SQUASHED" -b test/squashed origin/main
commit_on "$SQUASHED" p4
squash_into_main test/squashed
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ ! -d "$SQUASHED" ]]; then pass "directory removed"; else fail "directory still present"; rm -rf "$SQUASHED"; fi
if git -C "$TARGET" show-ref --quiet refs/heads/test/squashed; then
  fail "branch still exists"; git -C "$TARGET" branch -D test/squashed >/dev/null 2>&1 || true
else
  pass "branch deleted"
fi
if grep -q 'merge=squash' "$AUDIT_LOG"; then pass "audit log records merge=squash"; else fail "audit log lacks merge=squash"; fi

# ── P5: unmerged tmp worktree with real commits is kept ──────────────────────
echo "P5: tmp worktree with an unmerged commit is never removed"
UNMERGED="/tmp/zts-sweep-test-unmerged-$$"
rm -rf "$UNMERGED"
git -C "$TARGET" worktree add -q "$UNMERGED" -b test/unmerged origin/main
commit_on "$UNMERGED" p5
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ -d "$UNMERGED" ]]; then pass "directory still present"; else fail "directory removed"; fi
if git -C "$TARGET" show-ref --quiet refs/heads/test/unmerged; then pass "branch kept"; else fail "branch deleted"; fi
git -C "$TARGET" worktree remove --force "$UNMERGED" 2>/dev/null || true
git -C "$TARGET" branch -D test/unmerged 2>/dev/null || true

# ── P6: squash-merged worktree under <repo>/.claude/worktrees is removed ─────
echo "P6: squash-merged clean worktree under the repo's .claude/worktrees is removed"
INREPO="$TARGET/.claude/worktrees/p6"
mkdir -p "$TARGET/.claude/worktrees"
git -C "$TARGET" worktree add -q "$INREPO" -b test/inrepo origin/main
commit_on "$INREPO" p6
squash_into_main test/inrepo
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ ! -d "$INREPO" ]]; then pass "directory removed"; else fail "directory still present"; fi
if git -C "$TARGET" worktree list | grep -q "$INREPO"; then fail "still registered"; else pass "deregistered from git worktree list"; fi

# ── P7: unmerged worktree under <repo>/.claude/worktrees is kept ─────────────
echo "P7: worktree under .claude/worktrees with an unmerged commit is never removed"
INREPO2="$TARGET/.claude/worktrees/p7"
git -C "$TARGET" worktree add -q "$INREPO2" -b test/inrepo-unmerged origin/main
commit_on "$INREPO2" p7
WORKTREE_AUDIT_LOG="$AUDIT_LOG" WORKTREE_GRACE_SECONDS=0 \
  "$MANAGER" sweep "$TARGET" >/dev/null 2>&1 || true
if [[ -d "$INREPO2" ]]; then pass "directory still present"; else fail "directory removed"; fi
if git -C "$TARGET" worktree list | grep -q "$INREPO2"; then pass "still registered in git worktree list"; else fail "deregistered"; fi


# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
[[ "$FAIL_COUNT" -eq 0 ]] || exit 1
