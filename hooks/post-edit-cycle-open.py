#!/usr/bin/env python3
"""post-edit-cycle-open.py -- PostToolUse hook: an edit opens a cycle task.

Owner decision 3 (2026-10-13): a task opens at the first Edit/Write on a file
of a git work tree (a file git does not ignore, see tools/cycle_ledger.py) and
closes when every engineering-loop stage is proven; ``stop-cycle-gate.py``
enforces the close. Edits outside any repository, or of ignored files (a
scratchpad, a venv, a memory file under ~/.claude), open nothing.

Identity. A subagent's tool events carry ``agent_id`` and ``agent_type``
(Claude Code hooks reference, "When a subagent calls a tool, tool events such
as PreToolUse and PostToolUse fire the same configured hooks ... and the input
carries the agent_id and agent_type common input fields"); their absence means
the main agent. One task is open per (session, agent) at a time.

Where. The row goes to the ledger of the session's ``cwd`` repository, the one
the Stop gate reads, whichever repository the edited file belongs to (the file's
repository is recorded as ``repo``). When the cwd is not inside a repository the
row goes to the file's repository and stderr says the Stop gate will not see it.

Pre: stdin is the PostToolUse event JSON. Post: exit 0 always (PostToolUse
cannot undo the edit); stderr names every outcome but the silent "not a task
file" and "task already open" cases.
"""
from __future__ import annotations

import json
import os
import sys

_TOOL = "cycle-open"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))


def say(message: str) -> None:
    print(f"[{_TOOL}] {message}", file=sys.stderr)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _opener(payload: dict, repo: str, file_path: str) -> dict:
    agent_id = _text(payload.get("agent_id")) or None
    return {"session_id": _text(payload.get("session_id")) or None, "agent_id": agent_id,
            "agent_type": _text(payload.get("agent_type")) or ("unknown" if agent_id else "main"),
            "transcript_path": _text(payload.get("agent_transcript_path")) or _text(payload.get("transcript_path")),
            "repo": repo, "first_path": file_path}


def _ledger(cycle_ledger, gates_jsonl, cwd: str, repo: str) -> str:
    try:
        return cycle_ledger.ledger_path(cwd)
    except gates_jsonl.LedgerError as exc:
        say(f"the session cwd is not in a repository ({exc}); the task is recorded in {repo} "
            "but the Stop gate reads the cwd's ledger and will NOT enforce it")
        return cycle_ledger.ledger_path(repo)


def main() -> int:
    try:
        import cycle_evidence
        import cycle_ledger
        import gates_jsonl
    except ImportError as exc:  # FAILS_ON: tools/ not shipped beside hooks/ (partial install)
        say(f"cannot load tools/cycle_*.py, no cycle task opened: {exc}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        say(f"stdin is not JSON, no cycle task opened: {exc}")
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") not in cycle_evidence.EDIT_TOOLS:
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    file_path = _text(tool_input.get("file_path")) or _text(tool_input.get("notebook_path"))
    cwd = _text(payload.get("cwd")) or os.getcwd()
    try:
        repo = cycle_ledger.task_repo(os.path.join(cwd, file_path)) if file_path else None
        if repo is None:
            return 0  # not a file of a work tree: no task, by decision 3
        opener = _opener(payload, repo, file_path)
        task, created = cycle_ledger.open_task(_ledger(cycle_ledger, gates_jsonl, cwd, repo), opener)
    except gates_jsonl.LedgerError as exc:
        say(f"cycle task NOT recorded, the Stop gate cannot enforce it: {exc}")
        return 0
    if created:
        if opener["session_id"] is None:
            say("payload carried no session_id: the task is unattributed and blocks every main-agent Stop")
        say(f"cycle task {task['open']} opened by {opener['agent_type']} at {file_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
