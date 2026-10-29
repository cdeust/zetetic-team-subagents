#!/usr/bin/env python3
"""checkpoint_summary.py — deterministic session checkpoint from a transcript.

Used by ``hooks/stop-context-guard.py``. The hook used to write an empty stub
and block the turn asking the model to spawn a scribe subagent to fill it in.
Owner decision (2026-10-21): the checkpoint needs a summary produced inside the
hook, not an agent. Every field below is MEASURED from data the hook can read
without a model: the transcript JSONL named in the hook input, and git.

  user requests   the last user-typed messages (tool results and harness
                  reminders are not requests and are skipped)
  files touched   file_path of Edit / Write / MultiEdit / NotebookEdit calls
  commands        the last Bash commands
  errors          tool_result blocks flagged is_error
  last assistant  the final assistant text block
  open todos      pending / in_progress items of the last TodoWrite call

A field that cannot be measured is rendered as ``(none found)``; nothing is
invented and nothing is delegated. The read is bounded to the transcript tail
(``MAX_BYTES``) so a 1 GB transcript cannot stall a Stop hook.
"""
from __future__ import annotations

import json
import os

MAX_BYTES = 4 * 1024 * 1024  # source: same cap as tools/transcript_scan.py MAX_BYTES (bounded Stop-hook read)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# source: letta summary schema budget (<=500 words total), see hooks/stop-context-guard.py
KEEP = {"requests": 5, "files": 30, "commands": 10, "errors": 5, "todos": 15}
# source: letta summary schema, quoted tool output clipped (2,000 chars max)
CLIP = {"request": 400, "command": 200, "error": 240, "assistant": 1500}
NONE_FOUND = "(none found)"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tail_lines(transcript_path):
    """Complete JSONL lines from the last MAX_BYTES of the file, oldest first."""
    try:
        size = os.stat(transcript_path).st_size
        with open(transcript_path, "rb") as fh:
            start = max(0, size - MAX_BYTES)
            fh.seek(start)
            data = fh.read().decode("utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return []
    lines = data.split("\n")
    if start > 0:
        lines = lines[1:]  # first segment is a partial line
    return lines


def _records(transcript_path):
    for line in _tail_lines(transcript_path):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _blocks(obj):
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _role(obj) -> str:
    return (obj.get("message") or {}).get("role") or obj.get("type") or ""


def _is_request(text: str) -> bool:
    text = text.strip()
    return bool(text) and not text.startswith("<") and not text.startswith("Caveat:")


def _ordered_unique_last(items):
    """Unique items ordered by their LAST occurrence (most recent last)."""
    seen, out = set(), []
    for item in reversed(items):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return list(reversed(out))


def _error_text(block) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return _clip(content or "", CLIP["error"])


def _todos(block) -> list[str]:
    todos = (block.get("input") or {}).get("todos") or []
    return [
        f"[{t.get('status')}] {_clip(t.get('content') or t.get('subject') or '', 200)}"
        for t in todos
        if isinstance(t, dict) and t.get("status") in ("pending", "in_progress")
    ]


def _tool_use(block, acc: dict) -> None:
    """Record what one tool_use block contributes: an edited file, a command, the todos."""
    name, args = block.get("name"), block.get("input") or {}
    path = args.get("file_path") or args.get("notebook_path")
    if name in EDIT_TOOLS and path:
        acc["files"].append(str(path))
    elif name == "Bash" and args.get("command"):
        acc["commands"].append(_clip(args["command"], CLIP["command"]))
    elif name == "TodoWrite":
        acc["todos"] = _todos(block)


def _absorb(block, role: str, acc: dict) -> None:
    """Fold one content block into the accumulator."""
    kind = block.get("type")
    text = block.get("text", "")
    if kind == "text" and role == "user" and _is_request(text):
        acc["requests"].append(_clip(text, CLIP["request"]))
    elif kind == "text" and role == "assistant" and text.strip():
        acc["last_assistant"] = _clip(text, CLIP["assistant"])
    elif kind == "tool_use":
        _tool_use(block, acc)
    elif kind == "tool_result" and block.get("is_error"):
        acc["errors"].append(_error_text(block))


def summarize(transcript_path) -> dict:
    """Measured session facts from the transcript tail. Pure apart from the read."""
    acc = {"requests": [], "files": [], "commands": [], "errors": [], "last_assistant": "", "todos": []}
    for obj in _records(transcript_path):
        role = _role(obj)
        for block in _blocks(obj):
            _absorb(block, role, acc)
    return {
        "user_requests": acc["requests"][-KEEP["requests"]:],
        "files_touched": _ordered_unique_last(acc["files"])[-KEEP["files"]:],
        "commands": acc["commands"][-KEEP["commands"]:],
        "errors": acc["errors"][-KEEP["errors"]:],
        "last_assistant": acc["last_assistant"],
        "open_todos": acc["todos"][:KEEP["todos"]],
    }


def _bullets(items, fmt="- {}") -> str:
    return "\n".join(fmt.format(i) for i in items) if items else NONE_FOUND


def render(facts: dict, session: dict) -> str:
    """The checkpoint markdown. ``session`` carries the hook's own measurements:
    level, iso, session_id, model, ctx, cwd, branch, last_commit, git_status."""
    status = [f"{l.strip()} (git)" for l in session.get("git_status", "").splitlines()]
    touched = facts["files_touched"] + [s for s in status if s]
    return f"""---
description: "Auto-checkpoint ({session['level']}) at {session['ctx']:,} tokens — session {session['session_id'][:8]} on {session['branch'] or 'unknown branch'}"
---
## Auto-checkpoint ({session['level']}) — {session['iso']}

> Written by stop-context-guard from the transcript and git. Every field is
> measured, none is model-written; a field that could not be measured says so.

### Goals (last user requests, oldest first)
{_bullets(facts['user_requests'])}

### File references (edited this session, then git status)
{_bullets(touched)}

### Commands run (last {KEEP['commands']})
{_bullets(facts['commands'], '- `{}`')}

### Errors and fixes (tool errors seen; the fix is in the commands and files above)
{_bullets(facts['errors'])}

### Current state
- session_id: {session['session_id']}
- model: {session['model'] or 'unknown'} · context tokens at trigger: {session['ctx']:,}
- working dir: {session['cwd']}
- branch: {session['branch'] or '(unknown)'} · last commit: {session['last_commit'] or '(none)'}
- last assistant message: {facts['last_assistant'] or NONE_FOUND}

### Next steps (open TODOs)
{_bullets(facts['open_todos'])}

### Resume contract
Read this checkpoint + ONE targeted, agent_topic-scoped cortex:recall. Do NOT
re-read files or docs this checkpoint already summarizes — trust the file
references above and verify with targeted Reads only when editing.
"""
