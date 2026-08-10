# Hooks: Automated Zetetic Enforcement

Hooks automatically enforce the zetetic standard at key workflow points. They are the differentiator: the epistemic standard is not voluntary; it is built into the development lifecycle.

## Installation

Copy the hooks configuration to your project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-commit-zetetic.sh",
        "timeout": 30000
      },
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-push-review.sh",
        "timeout": 60000
      },
      {
        "matcher": "Edit|Write",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-edit-layer-check.sh",
        "timeout": 10000
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/post-commit-difficulty.sh",
        "timeout": 15000
      },
      {
        "matcher": "Edit|Write",
        "command": "/path/to/zetetic-team-subagents/hooks/post-edit-balance.sh",
        "timeout": 10000
      }
    ],
    "Notification": [
      {
        "command": "/path/to/zetetic-team-subagents/hooks/notification-handler.sh",
        "timeout": 10000
      }
    ],
    "Stop": [
      {
        "command": "/path/to/zetetic-team-subagents/hooks/session-end.sh",
        "timeout": 15000
      }
    ]
  }
}
```

Replace `/path/to/zetetic-team-subagents` with the actual path to your clone.

## Hook Reference

| Hook | Event | What it does | Blocks? |
|------|-------|-------------|---------|
| **pre-commit-zetetic** | Before `git commit` | Scans staged files for invented constants, unsourced claims, TODOs without difficulty-book refs | Yes: violations block commit |
| **pre-tool-deletion-gate** | Before `Edit`/`Write` | Diffs old_string/content against the on-disk file; if the edit removes a top-level definition (Python/JS/TS/Rust/shell), searches the working tree for surviving callers. Tier 1 of `tools/deletion_gate.py`, catching the delete-with-live-callers pattern (cdeust/cortex-viz commit 45d4a80) at the moment of the edit, before it can land. Does not require a `Retired-Because:` trailer (no commit exists yet); that half of the contract is enforced at commit time by `.githooks/commit-msg` and at CI time by `tools/deletion-gate.sh`. Fails CLOSED (blocks) when it finds a removal but cannot verify whether a caller survives it; see the module docstring for why "the commit-time gate always catches it" cannot be assumed on this repo. | Yes: a surviving caller, or an unverifiable removal, blocks the edit (exit 2) |
| **post-tool-deletion-gate** | After `Edit`/`Write`/`Bash` | Tier 2: the net for a removal Tier 1 structurally cannot see, arrived via `sed`/`rm`/`git rm`/a patch (Bash), a whole-file `Write` with no `old_string`, or a multi-step accumulation. Diffs HEAD against the real on-disk working tree (`tools/deletion_gate.py --worktree`) after the tool call, regardless of which tool made the change. Cannot undo the change, but refuses the turn to continue silently until it is fixed. Same fail-closed-on-unverifiable discipline as Tier 1. | Yes: a surviving caller, or an unverifiable removal, blocks (exit 2) |
| **post-commit-difficulty** | After `git commit` | Checks if committed files relate to an active difficulty book; reminds to update | No: advisory |
| **pre-push-review** | Before `git push` | Runs zetetic checker on all changes since last push | Yes: violations block push |
| **session-start** | Session start | Loads repo state, difficulty books, agent worktrees, cached session | No: context injection |
| **session-end** | Session end (`Stop`) | Saves session summary to local cache and Cortex | No: background save |
| **stop-context-guard** | Session end (`Stop`) | Enforces the per-model token budget from `~/.claude/ctxguard-thresholds.json` (embedded fallback when absent): free mechanical checkpoint at the warn threshold (120K Fable/Haiku, 180K Opus/Sonnet); blocks once at the per-model hard cap (160K Fable, 170K Haiku, 200K Opus/Sonnet) and injects the checkpoint procedure. Ships in [session-optimizer](https://github.com/cdeust/session-optimizer); `session-start` seeds the config if absent. | At hard cap only: one-time, loop-safe |
| **pre-edit-layer-check** | Before `Edit`/`Write` | **Advisory reminder only.** Notes that a core/ file is being edited and, if the added text adds an outward (infrastructure/handlers/server) import, prints a sharper heads-up. It does NOT enforce the layer rule: real enforcement is the `tools/craftsmanship-checker.sh` LAYER_VIOLATION detector at commit/CI time. | No: advisory |
| **post-edit-balance** | After `Edit`/`Write` | Reminds to run /balance after editing pipeline files | No: advisory |
| **notification-handler** | Subagent completes | Logs result, checks for unmerged agent worktrees | No: informational |

## Session Start via CLAUDE.md

Since Claude Code has no `SessionStart` hook event, add this to your project's `CLAUDE.md`:

```markdown
## Session Start Protocol

At the beginning of every session:
1. Run `./hooks/session-start.sh` to load context
2. Call Cortex `query_methodology` for cognitive profile
3. Call Cortex `recall` with the project topic
4. Check difficulty books with `./tools/difficulty-book-manager.sh status`
```

## What the hooks enforce

The hooks are not style linters; they are epistemic enforcement:

1. **No invented constants.** Every hardcoded number must cite its source.
2. **No unsourced claims.** Comments containing "always," "never," "obviously" must cite evidence.
3. **No orphaned TODOs.** Every TODO must reference a difficulty-book entry or be explicitly tracked.
4. **Layer integrity (advisory reminder, not enforcement).** Editing a core/ file prints a heads-up about dependency direction (and a sharper note if the added text adds an outward import). The `pre-edit-layer-check` hook only greps the path/added lines; it does not parse the full import graph and never blocks. **Authoritative layer enforcement is the `tools/craftsmanship-checker.sh` LAYER_VIOLATION detector, run at commit/CI time** with full file contents.
5. **Data conservation.** Pipeline file edits trigger a reminder to verify mass-balance.
6. **Difficulty-book hygiene.** Commits and pushes check that hardest cases are addressed.
7. **Session continuity.** Context is saved and loaded across sessions.
