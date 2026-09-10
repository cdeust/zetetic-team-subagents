#!/usr/bin/env bash
# worktree-manager.sh — Manage agent worktrees
#
# Usage:
#   tools/worktree-manager.sh list                  # show active agent worktrees
#   tools/worktree-manager.sh cleanup               # remove merged agent/* worktrees (this repo)
#   tools/worktree-manager.sh status <agent-name>   # show last commit in worktree
#   tools/worktree-manager.sh sweep [--fetch] [repo ...]
#                                                    # remove merged tmp worktrees + stale
#                                                    # branches across one or more repos
#   tools/worktree-manager.sh inventory [repo ...]  # one line per worktree: merge state,
#                                                    # dirty count, age, size — what sweep
#                                                    # would remove and why the rest stays
#
# sweep contract:
#   - No repo args: discovers top-level git repos under the parent of this
#     repo (skips linked worktrees, identified by a `.git` FILE, not a dir).
#     `hooks/session-start.sh` never invokes this no-args form — it scopes
#     its automatic sweep to its own repo only (see issue #33 fix note
#     below); the multi-repo form is for deliberate, explicit hygiene runs.
#   - --fetch: runs `git fetch origin --prune` first (never on by default —
#     session-start calls sweep without it to avoid network at boot).
#   - A worktree is removed only if: its path is under /tmp, /private/tmp or
#     the repo's own `.claude/worktrees/` (never a deliberate ~/Developments
#     worktree), its branch is not `live/*` (dev-symlink targets), its branch
#     is merged into origin/main, its working tree is clean, AND it is older
#     than WORKTREE_GRACE_SECONDS (see below). Removal never uses --force.
#   - "Merged" means one of: the tip is an ancestor of origin/main, OR the
#     branch was squash-merged, detected offline by comparing the patch-id of
#     the branch's cumulative diff (merge-base..tip) with the patch-id of each
#     commit main gained since that merge-base (bounded by SQUASH_SCAN_LIMIT).
#     Measured 2026-09-10: every repo under anthropic-partnership squash-merges
#     its PRs, so the ancestor test alone had swept nothing in two months
#     (audit log: 2 lines) while 30 merged worktrees accumulated.
#   - Branch deletion uses `-d` for ancestors and `-D` only for a branch the
#     squash check proved merged; both are written to the audit log.
#   - After worktree removal, local branches merged into origin/main with no
#     worktree (excluding main/master/live/*/checked-out branches) are
#     deleted the same way.
#   - Every removal (and skip-by-grace-period) is appended to
#     ~/.claude/zetetic/worktree-sweep-audit.log for post-hoc attribution
#     (WORKTREE_AUDIT_LOG overrides the path; issue #136 moved it under zetetic/).
#
# ISSUE #33 ROOT CAUSE (fixed here, reproduced empirically 2026-07-17):
# `git merge-base --is-ancestor <branch> origin/main` returns TRUE for a
# brand-new branch that has zero commits beyond its base, because a freshly
# created worktree's branch tip equals origin/main's tip. Combined with a
# clean working tree (true before the agent's first edit), the old
# sweep_worktrees logic classified an untouched, minutes-old worktree as
# "merged + clean" and removed it — deregistering it from `git worktree
# list` and deleting its directory. Repro: `git worktree add /private/tmp/x
# -b test/repro origin/main` followed immediately by `sweep` removed it.
# The grace period below (WORKTREE_GRACE_SECONDS) closes this race by refusing
# to remove any worktree younger than the threshold, regardless of merge
# state. source: measured incident, issue #33 — reported loss occurred
# ~15-20 minutes after worktree creation; 3600s (60 min) gives a >=3x
# safety margin over the observed loss window.
#
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"; AGENT="${2:-}"

# source: measured incident, issue #33 (loss observed ~15-20 min post-creation;
# 3600s = 60 min gives >=3x safety margin). Override for tests only.
WORKTREE_GRACE_SECONDS="${WORKTREE_GRACE_SECONDS:-3600}"
# Upper bound on main commits scanned for a squash-merge match. source:
# measured 2026-09-10, the widest merge-base..origin/main gap among the 30
# stale worktrees was 23 commits (Cortex); 500 leaves a 20x margin while
# keeping the boot-time sweep bounded.
SQUASH_SCAN_LIMIT="${SQUASH_SCAN_LIMIT:-500}"
AUDIT_LOG="${WORKTREE_AUDIT_LOG:-$HOME/.claude/zetetic/worktree-sweep-audit.log}"

# Appends one audit line: ISO-timestamp, repo, path, branch, decision.
# Never fails the sweep — a log write failure is swallowed (best-effort).
audit_log() {
  local repo="$1" path="$2" branch="$3" decision="$4"
  mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null || true
  printf '%s\trepo=%s\tpath=%s\tbranch=%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$repo" "$path" "$branch" "$decision" \
    >>"$AUDIT_LOG" 2>/dev/null || true
}

# Portable directory age in seconds (birth time when the OS exposes it,
# else mtime as a documented fallback). macOS/BSD: `stat -f %B`. Linux with
# statx birth-time support: `stat -c %W` (returns 0 when unsupported, in
# which case we fall back to mtime `%Y`/`%m`).
#
# Dialect is detected first (`stat --version` succeeds only on GNU): on GNU
# coreutils `-f` means "file system status", so the former BSD-first probe
# printed a multi-line report into the arithmetic and the age came out
# empty. Under `[[ "" -lt N ]]` an empty age reads as 0, so on Linux every
# worktree looked younger than the grace period and was never swept.
# Reproduced 2026-09-10 in ubuntu:24.04 (coreutils 9.4).
worktree_age_seconds() {
  local path="$1" now created=""
  now="$(date +%s)"
  if stat --version >/dev/null 2>&1; then
    created="$(stat -c "%W" "$path" 2>/dev/null || true)"
    case "$created" in ''|0|-) created="$(stat -c "%Y" "$path" 2>/dev/null || echo "$now")" ;; esac
  else
    created="$(stat -f "%B" "$path" 2>/dev/null || true)"
    case "$created" in ''|0) created="$(stat -f "%m" "$path" 2>/dev/null || echo "$now")" ;; esac
  fi
  [[ "$created" =~ ^[0-9]+$ ]] || created="$now"
  echo $(( now - created ))
}

[[ -z "$ACTION" ]] && { echo "usage: $0 <list|cleanup|status|sweep|inventory> [args]" >&2; exit 2; }

# --- sweep helpers --------------------------------------------------------

# patch-id of one diff read on stdin; empty when the diff is empty.
_patch_id() { git patch-id --stable | awk '{print $1}'; }

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
  while IFS= read -r commit; do
    commit_id="$(git -C "$repo" diff "${commit}^" "$commit" 2>/dev/null | _patch_id)"
    [[ "$commit_id" == "$branch_id" ]] && return 0
  done < <(git -C "$repo" rev-list --max-count="$SQUASH_SCAN_LIMIT" "$base..origin/main" 2>/dev/null)
  return 1
}

# Echoes "ancestor", "squash" or nothing; exit 0 only when merged.
branch_merge_kind() {
  local repo="$1" branch="$2"
  if git -C "$repo" merge-base --is-ancestor "$branch" origin/main 2>/dev/null; then
    echo ancestor; return 0
  fi
  if branch_squash_merged "$repo" "$branch"; then
    echo squash; return 0
  fi
  return 1
}

# Deletes a merged branch: -d for an ancestor, -D only for a proven squash merge.
delete_merged_branch() {
  local repo="$1" branch="$2" kind="$3"
  if [[ "$kind" == "squash" ]]; then
    git -C "$repo" branch -D "$branch" >/dev/null 2>&1
  else
    git -C "$repo" branch -d "$branch" >/dev/null 2>&1
  fi
}

# True for the only two places an agent worktree may live: the system tmp
# roots and the repo's own `.claude/worktrees/` (the owner rule since
# 2026-09-08, and the directory Claude Code's own sweep looks at).
sweepable_path() {
  local path="$1" primary="$2"
  case "$path" in
    /tmp/*|/private/tmp/*|"$primary"/.claude/worktrees/*) return 0 ;;
    *) return 1 ;;
  esac
}

# Prints "<path>\t<branch>" one per worktree (branch empty/"(detached)" if unnamed).
list_worktrees() {
  local repo="$1"
  git -C "$repo" worktree list --porcelain 2>/dev/null | awk '
    /^worktree / { if (path != "") print path "\t" branch;
                   path=$2; branch="" }
    /^branch /   { b=$2; sub("refs/heads/", "", b); branch=b }
    /^detached$/ { branch="(detached)" }
    END { if (path != "") print path "\t" branch }
  '
}

# Removes merged, clean, tmp-path worktrees for one repo. Echoes one line per
# decision. Returns 1 only on an unexpected command failure, not on skips.
sweep_worktrees() {
  local repo="$1" primary="$2" primary_branch="$3"
  local removed=0 path branch rc=0 age
  # Physical paths on both sides: git reports worktrees resolved through
  # symlinks (macOS /var -> /private/var), the caller's repo path may not be.
  primary="$(cd "$primary" 2>/dev/null && pwd -P || echo "$primary")"
  while IFS=$'\t' read -r path branch; do
    [[ -z "$path" ]] && continue
    path="$(cd "$path" 2>/dev/null && pwd -P || echo "$path")"
    [[ "$path" == "$primary" ]] && continue

    if [[ -z "$branch" || "$branch" == "(detached)" ]]; then
      echo "  skip $path: detached HEAD"; continue
    fi
    if [[ "$branch" == "$primary_branch" ]]; then
      echo "  skip $path: current branch of primary worktree"; continue
    fi
    if [[ "$branch" == live/* ]]; then
      echo "  skip $path: protected branch ($branch)"; continue
    fi
    if ! sweepable_path "$path" "$primary"; then
      echo "  skip $path: not under /tmp or .claude/worktrees (deliberate worktree)"; continue
    fi
    # Root-cause fix (issue #33): a brand-new branch with zero commits is
    # (by definition of its tip) an ancestor of origin/main, so the
    # merge-check below cannot by itself distinguish "already merged, safe
    # to remove" from "just created, not yet worked on". Refuse removal until the worktree has
    # existed for WORKTREE_GRACE_SECONDS regardless of merge/clean state.
    age="$(worktree_age_seconds "$path")"
    if [[ "$age" -lt "$WORKTREE_GRACE_SECONDS" ]]; then
      echo "  skip $path ($branch): within grace period (age ${age}s < ${WORKTREE_GRACE_SECONDS}s)"
      audit_log "$repo" "$path" "$branch" "skip-grace-period age=${age}s"
      continue
    fi
    local kind
    if ! kind="$(branch_merge_kind "$repo" "$branch")"; then
      echo "  skip $path ($branch): not merged into origin/main"; continue
    fi
    if [[ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]]; then
      echo "  skip $path ($branch): dirty working tree"; continue
    fi

    echo "  remove $path ($branch): merged ($kind) + clean"
    if git -C "$repo" worktree remove "$path" 2>/dev/null; then
      delete_merged_branch "$repo" "$branch" "$kind" || true
      removed=$((removed + 1))
      audit_log "$repo" "$path" "$branch" "removed merge=${kind} age=${age}s"
    else
      echo "  error: worktree remove failed for $path"
      audit_log "$repo" "$path" "$branch" "error-remove-failed age=${age}s"
      rc=1
    fi
  done < <(list_worktrees "$repo")
  echo "  removed: $removed worktree(s)"
  return "$rc"
}

# Deletes local branches merged into origin/main with no attached worktree.
sweep_stale_branches() {
  local repo="$1"; shift
  local kept=("$@") branch deleted=0

  while IFS= read -r branch; do
    [[ -z "$branch" ]] && continue
    case "$branch" in main|master|live/*) continue ;; esac
    local skip=0 k
    for k in "${kept[@]}"; do [[ "$branch" == "$k" ]] && { skip=1; break; }; done
    [[ "$skip" == "1" ]] && continue
    local kind
    if kind="$(branch_merge_kind "$repo" "$branch")"; then
      if delete_merged_branch "$repo" "$branch" "$kind"; then
        echo "  deleted branch: $branch (merged ($kind), no worktree)"
        audit_log "$repo" "-" "$branch" "deleted-branch merge=${kind}"
        deleted=$((deleted + 1))
      fi
    fi
  done < <(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/)
  echo "  branches deleted: $deleted"
}

sweep_repo() {
  local repo="$1" do_fetch="$2"
  repo="$(cd "$repo" 2>/dev/null && pwd)" || { echo "Repo: $1"; echo "  error: not a directory"; return 1; }
  echo "Repo: $repo"

  if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  skip: not a git repository"; return 1
  fi

  if [[ "$do_fetch" == "1" ]]; then
    if git -C "$repo" remote get-url origin >/dev/null 2>&1; then
      git -C "$repo" fetch origin --prune >/dev/null 2>&1 || echo "  warn: fetch failed"
    else
      echo "  skip fetch: no origin remote"
    fi
  fi

  if ! git -C "$repo" rev-parse --verify origin/main >/dev/null 2>&1; then
    echo "  skip: no origin/main ref locally (fetch first)"
    return 0
  fi

  local primary_branch; primary_branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  local kept_branches=("$primary_branch")
  local path branch
  while IFS=$'\t' read -r path branch; do
    [[ -n "$branch" ]] && kept_branches+=("$branch")
  done < <(list_worktrees "$repo")

  local rc=0
  sweep_worktrees "$repo" "$repo" "$primary_branch" || rc=1
  sweep_stale_branches "$repo" "${kept_branches[@]}"
  return "$rc"
}

sweep_main() {
  local do_fetch=0 repos=() arg
  for arg in "$@"; do
    case "$arg" in
      --fetch) do_fetch=1 ;;
      *) repos+=("$arg") ;;
    esac
  done

  if [[ ${#repos[@]} -eq 0 ]]; then
    local parent d
    parent="$(dirname "$REPO_ROOT")"
    while IFS= read -r -d '' d; do
      [[ -d "$d/.git" ]] && repos+=("$d")
    done < <(find "$parent" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null)
  fi

  echo "Sweeping ${#repos[@]} repo(s)..."
  local rc=0 r
  if [[ ${#repos[@]} -gt 0 ]]; then
    for r in "${repos[@]}"; do
      sweep_repo "$r" "$do_fetch" || rc=1
      echo ""
    done
  fi
  return "$rc"
}

# --- inventory -------------------------------------------------------------

# One line per linked worktree of <repo>: what sweep would do and why.
# Columns: verdict, merge state, dirty file count, age in days, size, branch, path.
inventory_repo() {
  local repo="$1" primary path branch kind dirty age size verdict
  primary="$(cd "$repo" 2>/dev/null && pwd -P)" || return 1
  echo "Repo: $primary"
  while IFS=$'\t' read -r path branch; do
    [[ -z "$path" ]] && continue
    path="$(cd "$path" 2>/dev/null && pwd -P || echo "$path")"
    [[ "$path" == "$primary" ]] && continue
    kind="$(branch_merge_kind "$repo" "$branch" 2>/dev/null || echo unmerged)"
    dirty="$(git -C "$path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    age=$(( $(worktree_age_seconds "$path") / 86400 ))
    size="$(du -sh "$path" 2>/dev/null | cut -f1)"
    verdict="keep"
    if ! sweepable_path "$path" "$primary"; then verdict="keep:deliberate-path"
    elif [[ "$kind" == "unmerged" ]]; then verdict="keep:unmerged"
    elif [[ "$dirty" != "0" ]]; then verdict="keep:dirty"
    else verdict="sweep"; fi
    printf '  %-22s %-9s dirty=%-5s age=%3sd %6s  %s  %s\n' \
      "$verdict" "$kind" "$dirty" "$age" "$size" "$branch" "$path"
  done < <(list_worktrees "$repo")
}

inventory_main() {
  local repos=("$@") r
  [[ ${#repos[@]} -eq 0 ]] && repos=("$REPO_ROOT")
  for r in "${repos[@]}"; do
    [[ -d "$r/.git" || -f "$r/.git" ]] || { echo "Repo: $r"; echo "  skip: not a git repository"; continue; }
    if ! git -C "$r" rev-parse --verify origin/main >/dev/null 2>&1; then
      echo "Repo: $r"; echo "  skip: no origin/main ref locally (fetch first)"; continue
    fi
    inventory_repo "$r"
    echo ""
  done
}

# --- dispatch --------------------------------------------------------------

case "$ACTION" in
  list)
    echo "Active agent worktrees:"
    git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "agent/" || echo "  (none)"
    ;;

  cleanup)
    echo "Cleaning up merged agent worktrees..."
    cleaned=0
    while IFS= read -r line; do
      path=$(echo "$line" | awk '{print $1}')
      branch=$(echo "$line" | awk '{print $3}' | tr -d '[]')
      [[ "$branch" != agent/* ]] && continue
      # Check if branch is merged into current
      if git -C "$REPO_ROOT" branch --merged 2>/dev/null | grep -q "${branch#*/}" 2>/dev/null; then
        echo "  Removing: $path ($branch)"
        git -C "$REPO_ROOT" worktree remove "$path" 2>/dev/null || true
        git -C "$REPO_ROOT" branch -d "$branch" 2>/dev/null || true
        cleaned=$((cleaned + 1))
      fi
    done < <(git -C "$REPO_ROOT" worktree list 2>/dev/null)
    echo "Cleaned $cleaned worktree(s)."
    ;;

  status)
    [[ -z "$AGENT" ]] && { echo "usage: $0 status <agent-name>" >&2; exit 2; }
    worktree=$(git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "$AGENT" | head -1 | awk '{print $1}')
    if [[ -z "$worktree" ]]; then
      echo "No active worktree for agent: $AGENT"
      exit 1
    fi
    echo "Agent: $AGENT"
    echo "Path: $worktree"
    echo "Last commit: $(git -C "$worktree" log --oneline -1 2>/dev/null || echo 'none')"
    echo "Uncommitted: $(git -C "$worktree" status --porcelain 2>/dev/null | wc -l | tr -d ' ') files"
    ;;

  sweep)
    shift
    sweep_main "$@"
    ;;

  inventory)
    shift
    inventory_main "$@"
    ;;

  *) echo "usage: $0 <list|cleanup|status|sweep|inventory> [args]" >&2; exit 2 ;;
esac
