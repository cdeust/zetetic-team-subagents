# shellcheck shell=bash
# shellcheck disable=SC2034  # MERGE_KIND is read by the sourcing tool
# branch-merge.sh — is a local branch merged into origin/main? Sourced by
# tools/worktree-manager.sh, never executed. Expects SQUASH_SCAN_LIMIT.

# patch-id of one diff read on stdin; empty when the diff is empty.
_patch_id() { git patch-id --stable | awk '{print $1}'; }

# "<patch-id> <commit>" for each of the SQUASH_SCAN_LIMIT newest commits of
# origin/main, computed ONCE per repo by one `git log -p | git patch-id`
# pipeline. Forking a diff + patch-id per main commit per unmerged branch cost
# 94 s on Cortex (31 branches x up to 500 commits, measured 2026-10-15) and
# spent the whole 8 s boot budget; this is two processes however long main is.
# A merge commit contributes its diff against its first parent, as before.
SQUASH_INDEX=""
SQUASH_INDEX_REPO=""
squash_index() {
  local repo="$1"
  if [[ "$SQUASH_INDEX_REPO" != "$repo" ]]; then
    SQUASH_INDEX="$(git -C "$repo" log -p --no-color --no-ext-diff --diff-merges=first-parent \
      --max-count="$SQUASH_SCAN_LIMIT" origin/main 2>/dev/null | git patch-id --stable || true)"
    SQUASH_INDEX_REPO="$repo"
  fi
}

# True when <branch> was squash-merged into origin/main: the patch-id of its
# cumulative diff equals the patch-id of one commit main gained since their
# merge-base. Conservative by construction: a branch rebased across an
# overlapping hunk yields a different patch-id and is kept.
branch_squash_merged() {
  local repo="$1" branch="$2" base tip branch_id commit_id commit
  base="$(git -C "$repo" merge-base "$branch" origin/main 2>/dev/null)" || return 1
  tip="$(git -C "$repo" rev-parse "$branch" 2>/dev/null)" || return 1
  [[ "$base" == "$tip" ]] && return 1
  branch_id="$(git -C "$repo" diff "$base" "$tip" 2>/dev/null | _patch_id)"
  [[ -n "$branch_id" ]] || return 1
  squash_index "$repo"
  while read -r commit_id commit; do
    [[ "$commit_id" == "$branch_id" ]] || continue
    # the match must have landed after the merge-base, as the old range base..origin/main required
    local in_base=0
    git -C "$repo" merge-base --is-ancestor "$commit" "$base" >/dev/null 2>&1 || in_base=$?
    [[ "$in_base" == "1" ]] && return 0  # 1 = not an ancestor of base; other non-zero = git error, keep the branch
  done <<< "$SQUASH_INDEX"
  return 1
}

# Sets MERGE_KIND to "ancestor" or "squash" and returns 0 only when merged.
# It reports through a variable, not stdout, and must be called in the current
# shell: inside `$(...)` the lazily built SQUASH_INDEX would be lost with the
# subshell and rebuilt for every branch (measured 2026-10-15: 210 git
# processes and 35 s on Cortex instead of 2 and 1 s).
MERGE_KIND=""
branch_merge_kind() {
  local repo="$1" branch="$2"
  MERGE_KIND=""
  if git -C "$repo" merge-base --is-ancestor "$branch" origin/main 2>/dev/null; then
    MERGE_KIND=ancestor; return 0
  fi
  if branch_squash_merged "$repo" "$branch"; then
    MERGE_KIND=squash; return 0
  fi
  return 1
}

