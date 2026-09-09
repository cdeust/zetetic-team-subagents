# Clean Agent Worktrees

Remove merged agent worktree branches and their working directories.

## Instructions

1. Run `tools/worktree-manager.sh cleanup` to find and remove merged `agent/*`
   worktree branches in **this** repo only.

2. Report what was cleaned up.

3. If no merged worktrees found, say so.

## `cleanup` vs `sweep`

`cleanup` and `sweep` are two different scopes — use the one that matches
the situation:

| | `cleanup` | `sweep [--fetch] [repo ...]` |
|---|---|---|
| Scope | This repo only | This repo, an explicit list, or every top-level git repo discovered under this repo's parent directory |
| Branch filter | Only `agent/*` branches | Any branch, except `main`/`master`/`live/*` (dev-symlink mount targets) |
| Path filter | None | Only worktrees under `/tmp`, `/private/tmp` or the repo's own `.claude/worktrees/` — worktrees elsewhere (e.g. `~/Developments/...-live`, `...-wt-baseline`) are always left alone |
| Merge check | `git branch --merged` against the current branch | `git merge-base --is-ancestor <tip> origin/main`, or a squash merge proven by patch-id equality between the branch's cumulative diff and a commit `origin/main` gained since the merge-base |
| Stale branches (no worktree) | Not handled | Deleted with `git branch -d` if merged into `origin/main` |
| Network | Never | Only with `--fetch` |
| Safety | Never `--force` / `-D` | Never `--force`; `-D` only for a squash-proven branch, written to the audit log; never the current branch; never the primary worktree |

Before sweeping, `tools/worktree-manager.sh inventory [repo ...]` prints one
line per worktree with the verdict sweep will apply and why (`sweep`,
`keep:unmerged`, `keep:dirty`, `keep:deliberate-path`), plus dirty count,
age, size, branch and path.

Run `tools/worktree-manager.sh sweep` with no arguments to sweep every repo
discovered as a sibling of the current repo — this is what
`hooks/session-start.sh` does automatically (without `--fetch`) at the start
of every session, so tmp worktrees whose PR already merged rarely need a
manual pass.

## Dev symlink montage doctor

`tools/dev-symlink-doctor.sh [--repair]` checks (and can repair) the
"edition live" symlink montage between plugin cache installs
(`~/.claude/plugins/cache/...`) and their dev repos — see
`tools/dev-symlink.map.example` for the mapping format and the current
8 entries. `session-start.sh` runs it in check mode (warn-only) every
session; run it with `--repair` by hand after a plugin
install/update has overwritten a symlink with a fresh copy.

$ARGUMENTS
