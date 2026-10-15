# Worktree sweep: what it deletes, and what session start does

Owner rule (2026-10-15): no data loss. A tool deletes only what it can prove is
preserved elsewhere.

## Session start reports, it never deletes

The boot section `worktrees` (hooks/lib/session-sections.sh) runs
`tools/worktree-manager.sh report`. It lists stale worktrees and branches, one
line each, with the exact command that cleans them, and deletes nothing:

```
  stale: remove /repo/.claude/worktrees/w (feat/done): preserved (squash, on origin/main) + clean  -> run: bash /…/tools/worktree-manager.sh sweep /repo
```

Classifying a branch takes several git processes, so it is not done at boot. The
report (`tools/lib/worktree_report.py`) starts a detached task of kind `wtclass`
(`tools/lib/tasks.py`, [async-tasks.md](async-tasks.md)) keyed by a hash of the
repo's refs state (heads, remotes, worktree list). The task runs
`worktree-manager.sh sweep --dry-run`, the read-only mode of the explicit sweep's
own code, so the report and the sweep cannot disagree about a branch.

- The boot section prints the finished result for the current refs state.
- While that task runs it prints `classification running` and, when it has one,
  the last result it printed for an earlier refs state, marked `(earlier refs state)`.
- A failed task is printed as failed with the command to run by hand.
- Nothing waits, and no decision reads a clock.

The result is advisory: it is not recomputed when only a worktree's age or
dirtiness changes (the key is the refs state), and the explicit sweep re-checks
everything before it deletes.

## The explicit sweep deletes only preserved branches

`tools/worktree-manager.sh sweep [--fetch] [--dry-run] [repo ...]`. A branch is
deletable only when BOTH hold (`tools/lib/branch-merge.sh`):

1. Its changes are on `origin/main`: the tip is an ancestor, or
   `git merge-tree --write-tree origin/main <tip>` is clean and yields exactly
   `origin/main`'s tree (merging the branch changes nothing). `origin/main` is the
   remote, so this already proves the work is kept there; whether some remote ref
   still holds the branch's own tip adds no content safety and is not tested.
2. It is checked out nowhere (the sweep never offers the branch of a registered
   worktree to the branch pass, and git refuses a checked-out branch at deletion).

A branch that fails a condition is kept and the reason is printed. A worktree is
removed only with a preserved branch, and only if clean, aged past the grace
period and under `/tmp` or `<repo>/.claude/worktrees/`.

Deletion is `git branch -d`, never `-D`, against a private proof upstream
`refs/zetetic-sweep/proof-<pid>-<n>`: `origin/main`'s commit for an ancestor, and
for a squash a commit with `origin/main`'s own tree whose parents are `origin/main`
and the proven tip. Git therefore re-checks at deletion time that the tip it is
about to delete is the one that was proven (a commit added since is not reachable
from the proof and is refused). The proof ref is removed on every path.

### The persisted upstream is replaced, not appended to

`git checkout -b x origin/main` and `git worktree add -b x origin/main` persist
`branch.x.remote=origin` and `branch.x.merge=refs/heads/main`. `branch.<b>.merge`
is multi-valued, so a `-c branch.x.merge=<proof>` is appended after that value and
git reads the first one: the upstream resolved to local `main`, and `git branch -d`
called a squash-merged tip "not fully merged" (reproduced with git 2.50). The sweep
therefore rewrites `branch.<b>.remote` and `branch.<b>.merge` for the duration of
the delete. A successful delete removes the branch together with its config
section. A refused delete restores the saved values exactly and prints git's
reason (`keep branch: <b>: git branch -d refused it: ...`), on the worktree path
as well. The proof lives outside `refs/remotes` because git resolves a
`refs/remotes/<r>/*` upstream through remote `<r>`'s fetch refspec and misjudges a
squash merge the same way.

`--dry-run` runs the same classification (merge proof, registered worktrees) as the
real run and prints `would ...` for what the real run then does; tests run both
over the same repos (`tests/test_worktree_sweep_delete.py`). What a dry run cannot
know is a refusal by git itself at delete time (a commit added to the branch, a
checkout, since the classification); the real run prints that one.

A sweep killed with SIGKILL cannot clean up. Its proof ref stays and is purged at
the start of the next real sweep (a ref whose pid is still alive belongs to a
running sweep and stays). In the few milliseconds between rewriting the tracking
config and restoring it, a SIGKILL also leaves `branch.<b>.remote=.` and
`branch.<b>.merge=<the purged proof>` on that one branch; the branch is intact and
the next sweep deletes or keeps it as usual.

### Why not a patch-id

The previous test matched the patch-id of the branch's cumulative diff against
each of the last 500 commits of main and deleted with `git branch -D`. Review of
#165 reproduced two losses on scratch repos
(`tests/test_worktree_sweep_preserve.py`):

- a local-only branch whose whitespace-only change has the same patch-id as a
  different main commit (git ignores whitespace in a patch-id);
- a branch squash-merged and then reverted on main: the matching commit is still
  in main's log, the work is not in main's tree.

The merge-tree test is false for both, and costs one git process per branch
whatever the length of main (`tests/test_worktree_sweep_cost.py`), so the
500-commit scan limit is gone.

### Consequence to know

After the PR merges, GitHub deletes the remote branch and `fetch --prune` drops
`refs/remotes/origin/<branch>`. A squash-merged branch whose remote ref is pruned
is still swept: the tree check proves its work is on `origin/main`. A branch
whose work is not on `origin/main` is kept whatever the remote says.

`sweep --dry-run` prints `would ...` lines, changes no ref, drops no marker and
writes no audit line.
