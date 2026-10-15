#!/usr/bin/env bash
# worktree-manager.sh — Manage agent worktrees
#
# Usage:
#   tools/worktree-manager.sh list                  # show active agent worktrees
#   tools/worktree-manager.sh cleanup               # remove merged agent/* worktrees (this repo)
#   tools/worktree-manager.sh status <agent-name>   # show last commit in worktree
#   tools/worktree-manager.sh sweep [--fetch] [--dry-run] [repo ...]
#                                                    # remove preserved tmp worktrees + stale
#                                                    # branches across one or more repos;
#                                                    # --dry-run prints "would ..." and changes nothing
#   tools/worktree-manager.sh report [repo]         # the boot report: only REPORTS what sweep
#                                                    # would clean, deletes nothing (lib/worktree_report.py)
#   tools/worktree-manager.sh inventory [repo ...]  # one line per worktree: merge state,
#                                                    # dirty count, age, size — what sweep
#                                                    # would remove and why the rest stays
#
# sweep contract:
#   - No repo args: discovers top-level git repos under the parent of this
#     repo (skips linked worktrees, identified by a `.git` FILE, not a dir).
#     `hooks/session-start.sh` never runs sweep at all: it runs `report`, which
#     deletes nothing. Sweep is a deliberate, explicit hygiene run.
#   - --fetch: runs `git fetch origin --prune` first (never on by default —
#     session-start calls sweep without it to avoid network at boot).
#   - A worktree is removed only if: its path is under /tmp, /private/tmp or
#     the repo's own `.claude/worktrees/` (never a deliberate ~/Developments
#     worktree), its branch is not `live/*` (dev-symlink targets), its branch is
#     PRESERVED (below), its working tree is clean, AND it is older than
#     WORKTREE_GRACE_SECONDS (see below). Removal never uses --force.
#   - A branch is PRESERVED, and so deletable, only when its changes are on
#     origin/main (an ancestor, or a clean merge-tree no-op) and it is checked out
#     nowhere; otherwise it is kept and the reason is printed, on the worktree
#     path too. Deletion is `git branch -d`,
#     never -D. The proof and why a patch-id is no proof: docs/worktree-sweep.md.
#   - After worktree removal, preserved local branches with no worktree
#     (excluding main/master/live/*/checked-out branches) are deleted likewise.
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
# 1 for `sweep --dry-run`: every decision is printed as "would ...", nothing is
# changed, no marker is dropped and nothing is logged.
DRY_RUN=0
AUDIT_LOG="${WORKTREE_AUDIT_LOG:-$HOME/.claude/zetetic/worktree-sweep-audit.log}"

# Appends one audit line: ISO-timestamp, repo, path, branch, decision.
# Never fails the sweep — a log write failure is swallowed (best-effort).
audit_log() {
  local repo="$1" path="$2" branch="$3" decision="$4"
  [[ "$DRY_RUN" == "1" ]] && return 0
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

[[ -z "$ACTION" ]] && { echo "usage: $0 <list|cleanup|status|sweep|report|inventory> [args]" >&2; exit 2; }

# --- sweep helpers --------------------------------------------------------

# shellcheck source=lib/branch-merge.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/branch-merge.sh"

# Marker a sweep drops in a worktree's admin directory (<common>/worktrees/<id>)
# BEFORE deleting the checkout. A sweep SIGKILLed half way (the 8 s boot budget
# of hooks/lib/run_sections.py) leaves it behind. It is EVIDENCE FOR A HUMAN
# only: no sweep deletes on its strength, because the wreck cannot prove the
# user added nothing since (a lock, status.showUntrackedFiles=no, empty
# untracked directories and a stale marker each defeated a deleting resume).
REMOVING_MARKER="zetetic-sweep-removing"

# Admin directory of the registered worktree at <path>: the <common>/worktrees/<id>
# whose `gitdir` file names <path>/.git. Echoes it; exit 1 when none matches.
worktree_admin_dir() {
  local repo="$1" path="$2" common f
  common="$(cd "$repo" && cd "$(git rev-parse --git-common-dir)" && pwd -P)" || return 1
  for f in "$common"/worktrees/*/gitdir; do
    [[ -f "$f" ]] || continue
    if [[ "$(<"$f")" == "$path/.git" ]]; then dirname "$f"; return 0; fi
  done
  return 1
}

# Why the live checkout at <path> holds what `git worktree remove` would delete.
# Echoes the reason; exit 0 when there is one, 1 when provably clean.
# pre  = <path> is a directory whose .git link works.
# post = status is read with --untracked-files=all and --ignored on the command
#        line, which beats `status.showUntrackedFiles=no` in any config; an empty
#        directory (invisible to status) counts as the user's; a failing status
#        counts as not clean: unprovable is dirty.
checkout_holds_user_data() {
  local path="$1" status empty
  if ! status="$(git -C "$path" status --porcelain --untracked-files=all --ignored 2>/dev/null)"; then
    echo "git status failed"; return 0
  fi
  if [[ -n "$status" ]]; then echo "dirty working tree"; return 0; fi
  empty="$(find "$path" -name .git -prune -o -type d -empty -print -quit 2>/dev/null)"
  if [[ -n "$empty" ]]; then echo "empty untracked directory ${empty#"$path"/}"; return 0; fi
  return 1
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

# One report line for a registered worktree the sweep must not touch and a
# human must resolve: <what> is wrong, the commands finish the job.
report_for_human() {
  local repo="$1" path="$2" branch="$3" what="$4"
  echo "  skip $path ($branch): $what. Nothing was deleted. After inspecting it, finish with: git -C $repo worktree remove --force $path (if the directory is already gone: git -C $repo worktree prune --expire now, which drops EVERY registered worktree whose directory is missing, so read git worktree list first)"
}

# Removes one worktree whose branch is preserved (branch_preserved set MERGE_KIND
# and the proof objects) and clean. Echoes one line. Returns 0 removed (or, in
# --dry-run, would be removed), 1 kept (reason echoed), 2 removal failed.
# pre  = <path> is a sweepable, non-primary, aged worktree of <repo>.
# post = 0: checkout and admin directory are gone and the branch is deleted; if git
#        refused the branch delete the line "keep branch: <b>: <reason>" says so.
#        1/2: nothing was deleted and `git worktree prune` never ran.
remove_merged_worktree() {
  local repo="$1" raw_path="$2" path="$3" branch="$4" kind="$5" age="$6" admin="" why="" dir_state link_state
  admin="$(worktree_admin_dir "$repo" "$raw_path" || true)"
  # The sweep's marker (an interrupted removal), a missing directory and a
  # missing .git link are only REPORTED; the marker stays so the report repeats.
  if [[ -n "$admin" && -e "$admin/$REMOVING_MARKER" ]]; then
    dir_state=missing; [[ -d "$path" ]] && dir_state=present
    link_state=missing; [[ -e "$path/.git" ]] && link_state=present
    report_for_human "$repo" "$path" "$branch" "interrupted removal (sweep marker present; directory $dir_state, .git link $link_state)"
    audit_log "$repo" "$path" "$branch" "skip-interrupted-removal age=${age}s"
    return 1
  fi
  if [[ ! -d "$path" ]]; then
    report_for_human "$repo" "$path" "$branch" "registered worktree whose directory is missing and no sweep marker"
    return 1
  fi
  if [[ ! -e "$path/.git" ]]; then
    # `git -C` here would read the PRIMARY repo and call the directory dirty.
    report_for_human "$repo" "$path" "$branch" "registered worktree has no .git link and no sweep marker"
    return 1
  fi
  if why="$(checkout_holds_user_data "$path")"; then
    echo "  skip $path ($branch): $why"; return 1
  fi
  if [[ -z "$admin" ]]; then
    echo "  skip $path ($branch): cannot locate its admin directory under .git/worktrees"; return 1
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  would remove $path ($branch): preserved ($kind, on origin/main) + clean"; return 0
  fi
  echo "  remove $path ($branch): preserved ($kind, on origin/main) + clean"
  : >"$admin/$REMOVING_MARKER"
  if git -C "$repo" worktree remove "$path" 2>/dev/null; then
    if delete_preserved_branch "$repo" "$branch" "$kind" "$MERGE_TIP" "$MERGE_MAIN" "$MERGE_TREE"; then
      audit_log "$repo" "$path" "$branch" "removed merge=${kind} main=${MERGE_MAIN} tip=${MERGE_TIP} age=${age}s"
    else
      echo "  keep branch: $branch: $DELETE_WHY"
      audit_log "$repo" "$path" "$branch" "removed-worktree-kept-branch merge=${kind} tip=${MERGE_TIP} age=${age}s"
    fi
    return 0
  fi
  # A clean failure leaves the checkout intact: the marker must not outlive it.
  rm -f "$admin/$REMOVING_MARKER"
  echo "  error: worktree remove failed for $path"
  audit_log "$repo" "$path" "$branch" "error-remove-failed age=${age}s"
  return 2
}

# Removes preserved, clean, tmp-path worktrees for one repo. Echoes one line per
# decision. Returns 1 only on an unexpected command failure, not on skips.
sweep_worktrees() {
  local repo="$1" primary="$2" primary_branch="$3"
  local removed=0 path branch rc=0 age
  # Physical paths on both sides: git reports worktrees resolved through
  # symlinks (macOS /var -> /private/var), the caller's repo path may not be.
  primary="$(cd "$primary" 2>/dev/null && pwd -P || echo "$primary")"
  local raw_path
  while IFS=$'\t' read -r path branch; do
    [[ -z "$path" ]] && continue
    raw_path="$path"
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
    if ! branch_preserved "$repo" "$branch"; then
      echo "  skip $path ($branch): $PRESERVED_WHY"; continue
    fi
    local outcome=0
    remove_merged_worktree "$repo" "$raw_path" "$path" "$branch" "$MERGE_KIND" "$age" || outcome=$?
    case "$outcome" in
      0) removed=$((removed + 1)) ;;
      2) rc=1 ;;
    esac
  done < <(list_worktrees "$repo")
  if [[ "$DRY_RUN" == "1" ]]; then echo "  worktrees that would be removed: $removed"
  else echo "  removed: $removed worktree(s)"; fi
  return "$rc"
}

# Deletes preserved local branches (see branch_preserved) with no attached worktree.
sweep_stale_branches() {
  local repo="$1"; shift
  local kept=("$@") branch deleted=0

  while IFS= read -r branch; do
    [[ -z "$branch" ]] && continue
    case "$branch" in main|master|live/*) continue ;; esac
    local skip=0 k
    for k in "${kept[@]}"; do [[ "$branch" == "$k" ]] && { skip=1; break; }; done
    [[ "$skip" == "1" ]] && continue
    if ! branch_preserved "$repo" "$branch"; then
      echo "  keep branch: $branch: $PRESERVED_WHY"; continue
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "  would delete branch: $branch (preserved ($MERGE_KIND, on origin/main), no worktree)"
      deleted=$((deleted + 1)); continue
    fi
    if delete_preserved_branch "$repo" "$branch" "$MERGE_KIND" "$MERGE_TIP" "$MERGE_MAIN" "$MERGE_TREE"; then
      echo "  deleted branch: $branch (preserved ($MERGE_KIND, on origin/main), no worktree)"
      audit_log "$repo" "-" "$branch" "deleted-branch merge=${MERGE_KIND} main=${MERGE_MAIN} tip=${MERGE_TIP}"
      deleted=$((deleted + 1))
    else
      echo "  keep branch: $branch: $DELETE_WHY"
    fi
  done < <(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/)
  if [[ "$DRY_RUN" == "1" ]]; then echo "  branches that would be deleted: $deleted"
  else echo "  branches deleted: $deleted"; fi
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

  [[ "$DRY_RUN" == "1" ]] || purge_stale_proof_refs "$repo"
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
      --dry-run) DRY_RUN=1 ;;
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
    if branch_preserved "$repo" "$branch" 2>/dev/null; then kind="$MERGE_KIND"; else kind="kept"; fi
    dirty="$(git -C "$path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    age=$(( $(worktree_age_seconds "$path") / 86400 ))
    size="$(du -sh "$path" 2>/dev/null | cut -f1)"
    verdict="keep"
    if ! sweepable_path "$path" "$primary"; then verdict="keep:deliberate-path"
    elif [[ "$kind" == "kept" ]]; then verdict="keep:not-preserved"
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

  report)
    shift
    exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/worktree_report.py" "${1:-$REPO_ROOT}"
    ;;

  *) echo "usage: $0 <list|cleanup|status|sweep|report|inventory> [args]" >&2; exit 2 ;;
esac
