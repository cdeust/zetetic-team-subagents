# shellcheck shell=bash
# shellcheck disable=SC2034  # MERGE_*, PRESERVED_WHY, DELETE_WHY are read by the sourcing tool
# branch-merge.sh — may a local branch be deleted without losing work? Sourced
# by tools/worktree-manager.sh, never executed. The proof and its rationale are
# in docs/worktree-sweep.md.

# A branch is deletable only when ALL hold:
#   1. its changes are on origin/main (tip is an ancestor, or merging the tip
#      into origin/main is a clean no-op, decided by `git merge-tree`), which
#      already proves the work is on the remote: no separate remote-ref test;
#   2. it is checked out nowhere (the sweep skips the branches of registered
#      worktrees; git refuses a checked-out branch at deletion regardless).

# Sets MERGE_KIND to "ancestor" or "squash" (net diff already on main) and returns 0,
# plus the objects the proof is built from: MERGE_TIP (the tip proven), MERGE_MAIN
# (origin/main's commit) and MERGE_TREE (the tree both sides agree on).
# Returns 1 with PRESERVED_WHY set when the changes are not provably on origin/main.
_changes_on_main() {
  local repo="$1" tip="$2" merged main_tree rc=0
  MERGE_TIP="$tip"
  MERGE_MAIN="$(git -C "$repo" rev-parse --verify "origin/main^{commit}" 2>/dev/null)" || {
    PRESERVED_WHY="origin/main unreadable"; return 1; }
  main_tree="$(git -C "$repo" rev-parse --verify "origin/main^{tree}" 2>/dev/null)" || {
    PRESERVED_WHY="origin/main tree unreadable"; return 1; }
  MERGE_TREE="$main_tree"
  if git -C "$repo" merge-base --is-ancestor "$tip" origin/main 2>/dev/null; then
    MERGE_KIND=ancestor; return 0
  fi
  merged="$(git -C "$repo" merge-tree --write-tree origin/main "$tip" 2>/dev/null)" || rc=$?
  if [[ "$rc" != "0" ]]; then
    PRESERVED_WHY="merging it into origin/main is not a clean no-op (conflict or git error), so its changes are not provably on main"
    return 1
  fi
  if [[ "${merged%%$'\n'*}" != "$main_tree" ]]; then
    PRESERVED_WHY="its changes are not all on origin/main (merging it would change main's tree)"
    return 1
  fi
  MERGE_KIND=squash
}

# Returns 0 when <branch> is provably preserved: MERGE_KIND (ancestor|squash),
# MERGE_TIP, MERGE_MAIN and MERGE_TREE are set. Returns 1 with PRESERVED_WHY
# naming the condition that failed. Reports through variables, not stdout: the
# caller must run it in the current shell.
MERGE_KIND=""
MERGE_TIP=""
MERGE_MAIN=""
MERGE_TREE=""
PRESERVED_WHY=""
DELETE_WHY=""
branch_preserved() {
  local repo="$1" branch="$2" tip
  MERGE_KIND=""; MERGE_TIP=""; MERGE_MAIN=""; MERGE_TREE=""; PRESERVED_WHY=""
  tip="$(git -C "$repo" rev-parse --verify -q "refs/heads/$branch^{commit}")" || {
    PRESERVED_WHY="no such local branch"; return 1; }
  _changes_on_main "$repo" "$tip"
}

# The commit `git branch -d` must find the tip reachable from. Echoes its sha.
# ancestor: origin/main itself. squash: a commit with origin/main's own tree and
# parents origin/main and the tip, so the tip is reachable from it and the tree
# check, not this commit, is what vouches for the content.
_proof_commit() {
  local repo="$1" kind="$2" tip="$3" main="$4" tree="$5"
  if [[ "$kind" == "ancestor" ]]; then echo "$main"; return 0; fi
  GIT_AUTHOR_NAME=zetetic-sweep GIT_AUTHOR_EMAIL=sweep@invalid GIT_AUTHOR_DATE="@0 +0000" \
  GIT_COMMITTER_NAME=zetetic-sweep GIT_COMMITTER_EMAIL=sweep@invalid GIT_COMMITTER_DATE="@0 +0000" \
    git -C "$repo" commit-tree "$tree" -p "$main" -p "$tip" -m "zetetic-sweep proof"
}

# Puts the branch's persisted tracking config back exactly as saved.
# $1 repo, $2 branch, $3 saved remote values (newline separated), $4 saved merge values.
_restore_tracking() {
  local repo="$1" branch="$2" remotes="$3" merges="$4" v
  git -C "$repo" config --unset-all "branch.${branch}.remote" 2>/dev/null || true
  git -C "$repo" config --unset-all "branch.${branch}.merge" 2>/dev/null || true
  if [[ -n "$remotes" ]]; then
    while IFS= read -r v; do git -C "$repo" config --add "branch.${branch}.remote" "$v"; done <<<"$remotes"
  fi
  if [[ -n "$merges" ]]; then
    while IFS= read -r v; do git -C "$repo" config --add "branch.${branch}.merge" "$v"; done <<<"$merges"
  fi
}

# Deletes a preserved branch with `git branch -d`, never -D, against the proof
# commit of branch_preserved (kind tip main tree = MERGE_KIND MERGE_TIP MERGE_MAIN
# MERGE_TREE). The proof is a private ref outside refs/remotes, used as the
# branch's upstream, so git itself refuses a tip not reachable from it (a commit
# added since the proof). Returns 0 deleted; 1 refused (checked out, tip moved since the proof), with DELETE_WHY
# carrying git's reason.
#
# Why the config is rewritten: branch.<b>.merge is multi-valued, so a
# `-c branch.<b>.merge=<proof>` APPENDS to the tracking a branch made with
# `checkout -b x origin/main` already persists (merge=refs/heads/main); git reads
# the first value, resolves the upstream to local main and calls a squash-merged
# tip "not fully merged" (reproduced, git 2.50). So remote and merge are replaced
# for the duration of the delete. Success removes the branch and its config
# section; a refusal restores the saved values exactly. Only a SIGKILL between
# the rewrite and the restore leaves the proof upstream behind (a few ms).
# Outside refs/remotes on purpose: git resolves a refs/remotes/<r>/* upstream
# through remote <r>'s fetch refspec and misjudges a squash merge the same way.
delete_preserved_branch() {
  local repo="$1" branch="$2" kind="$3" tip="$4" main="$5" tree="$6"
  local proof_sha proof remotes merges out="" log rc=0
  DELETE_WHY=""
  proof_sha="$(_proof_commit "$repo" "$kind" "$tip" "$main" "$tree")" || {
    DELETE_WHY="could not build the proof commit"; return 1; }
  proof="refs/zetetic-sweep/proof-$$-${RANDOM}"
  git -C "$repo" update-ref "$proof" "$proof_sha" "" || { DELETE_WHY="could not create the proof ref"; return 1; }
  remotes="$(git -C "$repo" config --get-all "branch.${branch}.remote" 2>/dev/null || true)"
  merges="$(git -C "$repo" config --get-all "branch.${branch}.merge" 2>/dev/null || true)"
  # A file, not $(...): git must stay a direct child of this shell.
  log="$(mktemp "${TMPDIR:-/tmp}/zetetic-sweep.XXXXXX")" || { DELETE_WHY="no temp file for git's message"; return 1; }
  if _set_proof_upstream "$repo" "$branch" "$proof"; then
    git -C "$repo" branch -d -- "$branch" >"$log" 2>&1 || rc=1
  else
    rc=1; echo "could not point the branch's upstream at the proof" >"$log"
  fi
  if [[ "$rc" != "0" ]]; then
    _restore_tracking "$repo" "$branch" "$remotes" "$merges"
    out="$(tr '\n' ' ' <"$log")"
    DELETE_WHY="git branch -d refused it: ${out% }"
  fi
  rm -f "$log"
  git -C "$repo" update-ref -d "$proof" "$proof_sha" >/dev/null 2>&1 || true
  return "$rc"
}

_set_proof_upstream() {
  local repo="$1" branch="$2" proof="$3"
  git -C "$repo" config --unset-all "branch.${branch}.remote" 2>/dev/null || true
  git -C "$repo" config --unset-all "branch.${branch}.merge" 2>/dev/null || true
  git -C "$repo" config "branch.${branch}.remote" . || return 1
  git -C "$repo" config "branch.${branch}.merge" "$proof"
}

# Removes the proof refs a sweep killed mid-delete left behind (SIGKILL cannot
# run the cleanup above). A ref is named proof-<pid>-<n>; one whose pid is still
# alive belongs to a running sweep and stays.
purge_stale_proof_refs() {
  local repo="$1" ref pid
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    pid="${ref#refs/zetetic-sweep/proof-}"; pid="${pid%%-*}"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then continue; fi
    git -C "$repo" update-ref -d "$ref" >/dev/null 2>&1 || true
  done < <(git -C "$repo" for-each-ref --format='%(refname)' refs/zetetic-sweep/ 2>/dev/null)
}
