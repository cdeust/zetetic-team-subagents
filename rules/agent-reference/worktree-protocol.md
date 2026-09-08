---
name: worktree-protocol
description: "Worktree commit procedure: staging rules, conventional-commit HEREDOC format, hook-failure recovery, reporting"
read_when: "Spawned in an isolated git worktree, before your first commit"
audience: team agents — loaded on demand via Read, never at spawn
---

When spawned in an isolated worktree, you are working on a dedicated branch.

**Worktree location: inside the repository, under `<repo>/.claude/worktrees/<name>/`. Nowhere
else.** That is the directory Claude Code's own worktree mechanism uses (`isolation: worktree` on
the Agent tool, `EnterWorktree`, `claude --worktree <name>`), and the only one its cleanup sweep
knows about; a worktree created anywhere else is invisible to that sweep and accumulates on disk.
So: never `/tmp` or `/private/tmp` (issue #33: `hooks/session-start.sh` runs
`tools/worktree-manager.sh sweep` there, and macOS reaps `/tmp` outside git's control, so an
in-progress worktree can lose its directory mid-task and be deregistered from `git worktree list`
with its uncommitted work); never a sibling directory beside the repo
(`<repo>/../<repo-name>-<agent>-<timestamp>`, the former `scripts/spawn-agent.sh` default); never
`~/.claude/worktrees/`. Owner correction, 2026-09-08: a green-software campaign had left 43
detached worktrees and 33 branch worktrees under `/private/tmp/cortex-green-*`, on top of earlier
`<repo>-wt-*` siblings, all outside the repo and all taking space nothing would reclaim; every
line of guidance that named an outside location was retired that day, this paragraph included.
`scripts/spawn-agent.sh` now creates its worktree under `<target-repo>/.claude/worktrees/` and
warns when that directory is not gitignored in the target; add `.claude/worktrees/` to the
repository's `.gitignore` in that case. `tools/worktree-manager.sh sweep` still clears `/tmp`
leftovers from older sessions.

After completing your changes:

1. Stage the specific files you modified: `git add <file1> <file2> ...` — never use `git add -A` or `git add .`
2. Commit with a conventional commit message using a HEREDOC:
   ```
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <description>

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"
   ```
   Types: feat, fix, refactor, test, docs, perf, chore
3. **Pushing is the orchestrator's call, stated in your delegation prompt. Follow it.** Push
   when the contract says to, and stop there; do not push when it does not.

   This line used to forbid pushing absolutely. That was a local invention, and it contradicted
   the dispatch contract every delegation actually carries, which ends the agent's work at the
   push so the orchestrator can query CI and re-engage it with the result. Corrected 2026-08-10,
   after the contradiction produced a security flag on an agent that had done exactly what its
   prompt told it to do.

   Anthropic's worktree documentation treats a pushed worktree branch as the ordinary case: the
   cleanup sweep "skips a worktree that still holds work: changed or untracked files, or
   unpushed commits", and a merged worktree is detected from "the remote branch the worktree
   pushed to" no longer existing. Neither describes pushing as out of bounds.

   **Rewriting history is different and still needs saying.** Force-pushing, amending a pushed
   commit, or rebasing requires the prompt to authorise it explicitly, name the branch, and say
   what must survive the rewrite. Absent that sentence, add a commit rather than reshaping one.
4. If a pre-commit hook fails, read the error output, fix the violation, re-stage, and create a new commit.
5. Report the list of changed files and your branch name in your final response.
