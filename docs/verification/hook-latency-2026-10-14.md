# Hook latency, zetetic-team-subagents, 2026-10-14

Measured with `python3 scripts/measure-hook-latency.py` (macOS, Darwin 25.6, python 3.14, 1 warm-up then 5 measured runs per hook, HOME and cwd isolated, memories copied from the real store: 38 scopes, 1793 files). "before" is 9014be4, "after" is this PR. Limits asked for: median over 1 s on UserPromptSubmit/PreToolUse/PostToolUse, over 3 s at SessionStart. This plugin registers no UserPromptSubmit hook. Differences of a few 0.1 s on hooks this PR does not touch are run-to-run noise of the machine.

| Event | Hook | before median s | before max s | after median s | after max s | timeout s | over limit (after) |
|---|---|---|---|---|---|---|---|
| PreToolUse | `pre-push-review.sh [command contains 'git push'] (Bash)` | 0.193 | 1.119 | 0.199 | 0.775 | 5 | no |
| PreToolUse | `pre-push-provenance.sh [command contains 'git push'] (Bash)` | 0.165 | 0.250 | 0.196 | 0.227 | 5 | no |
| PreToolUse | `zetetic-gates.py (Bash/Read/Grep/Edit/Write/NotebookEdit/exec_command/shell_command/apply_patch/mcp__.*)` | 0.355 | 1.199 | 0.365 | 0.399 | none (host default) | no |
| PostToolUse | `post-commit-difficulty.sh [command contains 'git commit'] (Bash)` | 0.248 | 0.266 | 0.430 | 1.559 | 5 | no |
| PostToolUse | `post-commit-lab-notebook.sh [command contains 'git commit'] (Bash)` | 0.193 | 0.952 | 0.221 | 0.283 | 5 | no |
| PostToolUse | `post-edit-balance.sh (Edit/Write)` | 0.059 | 0.067 | 0.038 | 0.069 | 5 | no |
| PostToolUse | `post-research-provenance.sh (WebFetch/WebSearch)` | 0.118 | 0.138 | 0.072 | 0.078 | 5 | no |
| PostToolUse | `zetetic-gates.py (Bash/Edit/Write/exec_command/shell_command/apply_patch)` | 0.413 | 0.464 | 0.394 | 0.795 | none (host default) | no |
| PostToolUse | `post-edit-cycle-open.py (Edit/Write/MultiEdit/NotebookEdit)` | 0.327 | 0.332 | 0.650 | 1.066 | 10 | no |
| PostToolUseFailure | `post-tool-error-routing.sh` | 0.135 | 0.166 | 0.254 | 0.318 | 5 | no |
| SessionStart | `session-start.sh` | 8.268 | 9.574 | 0.83-1.28 (4 batches of 5 runs) | 2.044 | 10 | no |
| SessionStart | `session-start-research.sh` | 0.501 | 0.622 | 0.389 | 0.511 | 10 | no |
| SessionStart | `zetetic-gates.py` | 0.197 | 0.223 | 0.169 | 0.182 | none (host default) | no |
| Stop | `stop-acceptance-gate.py` | 32.126 | 49.160 | 23.708 | 29.384 | 10 | no |
| Stop | `stop-zetetic-spine.py` | 0.308 | 0.792 | 0.149 | 0.179 | 10 | no |
| Stop | `session-end.sh` | 0.656 | 0.718 | 0.476 | 0.636 | 10 | no |
| Stop | `session-end-memory-drain.sh` | 0.849 | 1.159 | 0.139 | 0.165 | 10 | no |
| Stop | `zetetic-gates.py` | 0.483 | 0.711 | 0.302 | 0.367 | none (host default) | no |
| Stop | `stop-reflection-gate.py` | 0.284 | 0.478 | 0.224 | 0.247 | 10 | no |
| Stop | `stop-cycle-gate.py` | 0.303 | 0.909 | 0.184 | 0.263 | 10 | no |
| SubagentStop | `zetetic-gates.py` | 0.537 | 1.079 | 0.330 | 0.371 | none (host default) | no |
| SubagentStop | `stop-cycle-gate.py` | 0.257 | 1.552 | 0.237 | 0.258 | 10 | no |
| SubagentStop | `subagent-stop-reflection.py` | 0.208 | 0.283 | 0.221 | 0.242 | 15 | no |
| Notification | `notification-handler.sh` | 0.187 | 0.219 | 0.144 | 0.152 | 5 | no |

## Findings

- `session-start.sh`: median before/after in the table. Cause: `memory-tool.sh scopes` spawned two python interpreters and two `find`s per scope (38 scopes: 4.4 s alone). Now one process (`tools/lib/memory_acl.py`), output byte-identical for 6 agent/registry combinations. The runner replaces the shell watchdog.
- `stop-acceptance-gate.py`: 24 to 32 s median against a 10 s host timeout, before and after. Not touched: it is a Stop hook (outside the stated thresholds) and by design runs the whole acceptance gate (the repo test suite) whenever the tree is dirty, with internal budgets of 120 s (warn) and 900 s (block) that exceed its own 10 s host timeout. The host kills the hook at 10 s, before its WARN can print, so the WARN tier is inert whenever the tree is dirty. Making it fit (cheaper gate set, or a different timeout) is an owner decision about what the Stop gate may cost. The measurement tree is dirty on purpose (worst case); a clean tree returns at once.
- No PreToolUse or PostToolUse hook has a median above 1 s, before or after.
- The measurement script lives in `scripts/` (repo tooling), not `tools/` (the plugin surface shipped to users and counted by `tools/doc-count-check.sh`).
