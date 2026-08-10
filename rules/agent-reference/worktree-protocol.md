---
name: worktree-protocol
description: "Worktree commit procedure: staging rules, conventional-commit HEREDOC format, hook-failure recovery, reporting"
read_when: "Spawned in an isolated git worktree, before your first commit"
audience: team agents — loaded on demand via Read, never at spawn
---

When spawned in an isolated worktree, you are working on a dedicated branch.

**Worktree location — never `/tmp` or `/private/tmp` (issue #33).** `hooks/session-start.sh`
runs `tools/worktree-manager.sh sweep` on every session start, and macOS periodically
reaps `/tmp` contents outside git's control; a worktree placed there can lose its
directory and be cleanly deregistered from `git worktree list` mid-task, discarding
uncommitted work. `worktree-manager.sh`'s sweep now enforces a grace period (default
60 min, `WORKTREE_GRACE_SECONDS`) and is scoped to the booting repo only, but `/tmp`
remains unsafe for hours-long work because of the OS-level reaper, which git-based
tooling cannot protect against. Prefer `scripts/spawn-agent.sh`'s own convention — a
sibling directory next to the repo (`<repo>/../<repo-name>-<agent>-<timestamp>`,
already the default when spawned via that script) — since it is outside `/tmp`'s
reaper AND outside the auto-discovered sibling-repo set that `sweep`'s no-args form
walks (that set is repos directly under the *parent* of the target repo, e.g.
`~/Developments/anthropic-partnership/*`; a `<repo>-<agent>-<stamp>` sibling of the
repo itself is not itself a top-level git repo there, so it is never enumerated).
`~/.claude/worktrees/<repo-name>-wt-<slug>` is an acceptable alternative but has not
been verified equally durable — no script in this repo targets that path, but its
robustness under Claude Code's own session/sandbox lifecycle is unconfirmed; prefer
the sibling-directory convention when in doubt.

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
