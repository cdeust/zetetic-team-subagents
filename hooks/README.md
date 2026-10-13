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
| **stop-redaction-gate** | Every returned message (`Stop` and `SubagentStop`) | Runs `tools/redaction-checker.sh --stdin` on the turn's final assistant text (`last_assistant_message`; transcript fallback): the greppable half of `skills/writing/redaction.md` (em dashes, banned vocabulary, weasel and filler phrases, binary contrasts, throat-clearing setups, puffery, bold label bullets; English and French phrasings). Findings are quoted line by line with the pattern name. The mechanism is `tools/redaction_gate.py`, shared with `pre-tool-redaction-gate`. This is the enforcement point of the `<redaction-gate>` the prose-producing agents carry: a prompt section is advisory, a hook runs every time. The judgment half of the eval (nothing invented, every attribution sourced, ends on a concrete point) is handed back in the block reason for the rewrite. | Opt-in: `REDACTION_STOP_BLOCK=on` or `.redaction-gate.json` at the repo root blocks until the message is rewritten (loop-safe: never re-blocks a forced continuation). Default: warning on stderr; `REDACTION_STOP_WARN=off` silences. |
| **pre-tool-redaction-gate** | Every outbound action carrying prose (`PreToolUse` on `Bash` and `mcp__github__*`) | Extracts the text a `git commit` (`-m`, `-F`), a `gh pr/issue/release create/comment/review/edit` (`--body`, `--title`, `--notes`, `--body-file`) or a GitHub MCP call (`body`, `title`, `commit_message`) is about to publish and runs it through `tools/redaction-checker.sh --stdin`, the same detector set as `stop-redaction-gate`. A message and a commit body are held to one rule; the mechanism both hooks share lives in `tools/redaction_gate.py`. A command carrying none of those verbs exits immediately. | Same opt-in as the Stop gate: `REDACTION_STOP_BLOCK=on` or `.redaction-gate.json` refuses the action (exit 2) with the findings quoted for the rewrite. Default: warning on stderr; `REDACTION_STOP_WARN=off` silences. |
| **stop-context-guard** | Session end (`Stop`) | Enforces the per-model token budget from `~/.claude/ctxguard-thresholds.json` (embedded fallback when absent): free mechanical checkpoint at the warn threshold (120K Fable/Haiku, 180K Opus/Sonnet); blocks once at the per-model hard cap (160K Fable, 170K Haiku, 200K Opus/Sonnet) and injects the checkpoint procedure. Ships in [session-optimizer](https://github.com/cdeust/session-optimizer); `session-start` seeds the config if absent. | At hard cap only: one-time, loop-safe |
| **subagent-stop-reflection** | Every subagent stop (`SubagentStop`) | Schedules the reflection the owner asked for on 2026-10-13: after each action performed by an agent, a lesson is extracted so the agent does better next time. Identifies the run (`agent_id`, `agent_type`, `agent_transcript_path` from the payload, falling back to the transcript file name and the sibling `agent-<id>.meta.json`; every fallback is printed), appends a pending row (agent id and type, task description, transcript path, the final handback message, time) to `<git-common-dir>/zetetic-gates/reflections.jsonl`, and retains the run into Hindsight when `~/.hindsight/coding-agent.json` (override: `HINDSIGHT_CONFIG`) opts the cwd in, tagged `agent_type:<type>` and `source:subagent`, via `POST {apiUrl}/v1/default/banks/{bank}/memories`. When Hindsight is not configured for the cwd, or the server is down, the hook says so on stderr and records the status in the ledger row; it never fails silently and never exits non-zero (that would block the subagent). Mechanism: `tools/reflection_subagent.py`, `tools/reflection_hindsight.py`, `tools/reflection_ledger.py`. | No: schedules only. |
| **stop-reflection-gate** | Session end (`Stop`) | Blocks the orchestrator while this session has a pending reflection. The reason tells it, per entry, to read the subagent transcript, write ONE Cortex memory tagged `lesson-candidate` with `agent_topic=<agent type>` (the type exactly as recorded, for example `zetetic-team-subagents:engineer`) stating what worked, what failed and what to do differently, quoting transcript lines, then lift the entry with `python3 tools/reflection_ledger.py --cwd <repo> lift <agent_id> --memory-id <id>`. The lift refuses without a positive integer memory id, on an unknown agent and on an already lifted one. Loop-safe like the other Stop gates: a forced continuation (`stop_hook_active`) is never blocked again, the still-pending ids are printed on stderr. Pending rows of other sessions never block this one and are counted on stderr. Not folded into `stop-gate-ledger` (user level; blocks only with `scripts/gate.sh` plus unpushed work; lifted by a green proof) nor `stop-acceptance-gate` (opt-in `.abl-gate.json`): a reflection must block in any repository and is lifted by a stored lesson. | Yes while a reflection of this session is pending: one-time, loop-safe |
| **post-edit-cycle-open** | After `Edit`/`Write`/`MultiEdit`/`NotebookEdit` | Opens an engineering-cycle task (owner decision 2026-10-13) at the first edit of a file of a git work tree that git does not ignore; edits outside any repository or of ignored files open nothing. One task per (session, agent): a subagent's edit carries `agent_id` and `agent_type`, the main agent's does not. The row goes to `<git-common-dir>/zetetic-gates/cycles.jsonl` of the session cwd's repository, with the edited file's repository recorded beside it; when the cwd is not in a repository, stderr says the Stop gate will not see the task. Mechanism: `tools/cycle_ledger.py`. | No: records only. |
| **stop-cycle-gate** | Session end and every subagent stop (`Stop`, `SubagentStop`) | Closes the stopping agent's open cycle task when its transcript and declarations prove every stage of `/zetetic:engineering-loop`: a Cortex recall, a Read/Grep/Glob, the edit, the declared check run green after the last edit, a review (`/code-review` or a reviewer Agent) after the last edit, a Cortex remember after the first edit; the check command, the refined spec and the benchmark are declared with `python3 tools/cycle_ledger.py --cwd <repo> declare <task> --stage check|refine|benchmark`, each reference checked (a commit of the repository, a GitHub PR or issue URL, a positive Cortex memory id; the benchmark alone may be `--not-applicable "<reason>"`). Otherwise it blocks, listing each missing stage and how to prove it. A subagent is judged on its own transcript (`agent_transcript_path`). `tools/cycle_ledger.py metrics` prints the pre-registered metric per agent type: promise rate (stages closed on a declaration over stages closed) and reopens (reviews followed by another edit). Rules: `tools/cycle_evidence.py`. | Yes, by default (owner decision, overriding the warn-by-default lesson of 2026-06-10): blocks until proven; loop-safe on `stop_hook_active`. Emergency switch `ZETETIC_CYCLE_GATE=off` in Claude Code's environment; each stop it lets through appends a `bypass` row. |
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
