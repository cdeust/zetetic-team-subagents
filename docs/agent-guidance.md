# Agent guidance for zetetic-team-subagents

This is the former body of `CLAUDE.md`, moved here on 2026-09-08 so that it is read on
demand instead of being re-sent to the model on every turn (owner correction: CLAUDE.md
stays nearly empty; the host loads what it needs when it needs it). Nothing was removed
except the dangling "Global rules are imported, not restated" sentence and the two `@`
import lines under it, since those files are already loaded on demand by the host's
skills and agents rather than by this repository.

# zetetic-team-subagents

The plugin that defines the agents, skills, commands, hooks and rules every other
repository runs under. Python tooling, Markdown agent definitions.

## Repo-specific constraints

- **Any `.md` under `agents/` is parsed as an agent definition.** Non-agent documentation goes in `rules/`, never in `agents/`.
- **The zetetic spine is generated, not hand-edited.** `scripts/generate-spine.py` injects the `<zetetic-spine>` block into every anchor-bearing agent, delimited by HTML comments and idempotent, with `--check` for CI. Edit the generator, never the 97 outputs.
- **This clone is live-mounted as the installed plugin** - edits take effect immediately in running sessions. Never edit `~/.claude/plugins/cache`; change it here.
- **Hooks are the enforcement layer**, instructions are advisory. `hooks/stop-acceptance-gate.py` gates turn-end: it resolves the repo's own `tools/acceptance-gate.sh` or falls back to this plugin's, and blocks everywhere when `ABL_STOP_BLOCK=on`. Gate definitions live in `memory/acceptance-gates*.yaml`; the universal set is `acceptance-gates.global.yaml`.
- **`/zetetic:engineering-loop` is the mandatory entry point** for any request that touches code (`commands/zetetic/engineering-loop.md`). It names the three contract violations - "pre-existing", a skip, and a red PR - as refusals.

## Etiquette

Conventional commits, staged file-by-file. One PR per concern. A pull request merges when
CI is green and the review's last verdict on its head is an approve; the owner does not gate merges by hand.
CI is the authority: it exists to catch regressions and enforce the engineering standards.

## CI contract for agents and routines

This section binds every agent that works on this repository: an interactive session,
a scheduled routine, the local manager. It follows the contract of `cdeust/Cortex`, the
source of truth for CI. Where the prompt of a routine says otherwise, this section wins:
the prompt was written before the contract, and the repository's own standards apply.

1. **The review verdict decides the merge.** The `PR Review` workflow posts a comment by
   `claude[bot]` that ends with `Verdict: approve` or `Verdict: block`. The resolver merges
   a pull request whose last verdict covers its head, reads approve, and whose required
   checks are green. Two cases differ: a Dependabot minor or patch update merges on green
   required checks alone, and a title that contains "do not merge" is never merged. No
   agent merges by hand or enables auto-merge.
2. **Three reviews per pull request.** The budget counts the successful review runs of
   the pull request, so a push to an open pull request spends one. The `claude-rereview`
   label grants a fourth; it is the owner's to set, and the next push uses it. Push once
   per verdict, with every blocker of that verdict fixed, and never while a `PR Review`
   run is in progress on the pull request: the review would land on a commit that is no
   longer the head.
3. **Budget spent without an approve on the head: a new branch.** Push the same commits to
   `<branch>-r<N>`, open a pull request with the same title and body plus a "Continuation"
   section naming the old one, leave one "Continued in #n" line on the old one, close it.
   A forced push of any kind, `--force-with-lease` included, is never used: it does not
   reset the budget and it rewrites a branch another agent may hold.
4. **No comparison with the main branch.** Do not measure how far a branch is behind, do
   not rebase a pull request branch onto the main branch, do not use the branch-update
   button or its API, and do not write that a pull request is late: a late pull request
   merges. The only exception is a real conflict (`mergeable_state` is `dirty`): merge the
   main branch into the branch with a merge commit, resolve it, rerun the touched tests,
   check that the merge did not change the meaning of either side, and push normally.
5. **One pull request in flight.** A pull request is in flight while a check runs on it, a
   review runs on it, or an approve waits for the merge. While one is in flight, open no
   other pull request (issue, relaunch or next slice) and push to no other branch.
6. **No comment after an approve.** No reply to the notes, no summary, no acknowledgement.
   Notes marked "no action before merge" go to a follow-up pull request after the merge.
   Before an approve, comment only with a pushed fix or a hold.
7. **Owner decisions are left alone:** a pull request on the branch
   `ci/budget-counts-contract-reviews`, anything labelled `hold` or `do-not-merge`, a draft.
