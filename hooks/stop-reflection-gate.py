#!/usr/bin/env python3
"""stop-reflection-gate.py -- Stop hook: no stop while a reflection is pending.

Companion of ``subagent-stop-reflection.py``. Reads the per-repo ledger
``<git-common-dir>/zetetic-gates/reflections.jsonl`` and blocks the orchestrator's
stop while THIS session has a pending row, with the exact procedure:

  1. read the subagent transcript;
  2. write ONE Cortex memory tagged ``lesson-candidate`` with
     ``agent_topic=<agent type>`` (the type exactly as the ledger recorded it,
     e.g. ``zetetic-team-subagents:engineer``): what worked, what failed, what the
     agent should do differently next time, quoting transcript lines;
  3. lift the row: ``python3 <root>/tools/reflection_ledger.py lift <agent_id>
     --memory-id <id>``, which refuses without the memory id.

Why a new hook and not stop-gate-ledger / stop-acceptance-gate. The user-level
stop-gate-ledger only blocks when the repo has ``scripts/gate.sh`` AND work is
uncommitted or unpushed, and lifts on a green proof; stop-acceptance-gate runs
the acceptance gate and blocks only under ``.abl-gate.json``. A reflection must
block with or without either, and is lifted by a stored lesson, not a proof.
What IS reused is the ledger contract (append-only JSONL under
``zetetic-gates/``, a lifting row names the entry) and the loop rule below.

Loop rule, as in the other Stop gates: a turn already in a forced continuation
(``stop_hook_active``) is never blocked again; the still-pending rows are
reported on stderr instead. Rows of other sessions never block this one (the
ledger is per repository and sessions run in parallel); their count is reported.

Pre: stdin is the Stop event JSON. Post: stdout holds a block decision iff this
session has a pending row and stop_hook_active is false.
"""
from __future__ import annotations

import json
import os
import sys

_TOOL = "reflection-gate"
_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
# Listing every pending row would bury the instruction; the lift CLI's `list`
# shows the rest. source: stop-gate-ledger.py _MAX_LISTED (5).
MAX_LISTED = 5


def say(message: str) -> None:
    print(f"[{_TOOL}] {message}", file=sys.stderr)


def _entry_text(row: dict, cwd: str, lift_tool: str) -> str:
    return (f"- agent {row['agent_id']} (type: {row.get('agent_type', '?')}; "
            f"task: {row.get('description') or 'n/a'})\n"
            f"  transcript: {row.get('transcript_path') or 'unknown'}\n"
            f"  lift: python3 {lift_tool} --cwd {cwd} lift {row['agent_id']} --memory-id <id>")


def block_reason(rows: list, cwd: str) -> str:
    lift_tool = os.path.join(_ROOT, "tools", "reflection_ledger.py")
    shown = "\n".join(_entry_text(r, cwd, lift_tool) for r in rows[:MAX_LISTED])
    more = f"\n(+{len(rows) - MAX_LISTED} more: python3 {lift_tool} --cwd {cwd} list)" \
        if len(rows) > MAX_LISTED else ""
    return (
        f"{len(rows)} subagent reflection(s) pending. After each action by an agent, a "
        "lesson is extracted so the agent does better next time. Do it yourself now, "
        "not through a subagent (a subagent would add a pending reflection of its own). "
        "For EACH entry:\n"
        "1. Read the subagent transcript.\n"
        "2. Call Cortex `remember` ONCE with tags ['lesson-candidate'] and "
        "agent_topic=<the agent type shown>: what worked, what failed, and what the "
        "agent should do differently next time. Quote the transcript lines that prove "
        "each point; a lesson without a quoted line is an opinion.\n"
        "3. Run the lift command with the memory id `remember` returned. It refuses "
        "without one.\n" + shown + more)


def main() -> int:
    try:
        import reflection_ledger
    except ImportError as exc:  # FAILS_ON: tools/ not shipped beside hooks/ (partial install)
        say(f"cannot load tools/reflection_ledger.py, reflections not enforced: {exc}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        say(f"stdin is not JSON, reflections not enforced: {exc}")
        return 0
    if not isinstance(payload, dict):
        say("stdin is not a JSON object, reflections not enforced")
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
    try:
        path = reflection_ledger.ledger_path(cwd)
    except reflection_ledger.LedgerError:
        return 0  # not a git repository: no ledger can exist here, nothing is owed
    everything = reflection_ledger.pending(path)
    mine = reflection_ledger.pending(path, session) if session else everything
    elsewhere = len(everything) - len(mine)
    if elsewhere:
        say(f"{elsewhere} pending reflection(s) belong to other sessions: "
            f"python3 {os.path.join(_ROOT, 'tools', 'reflection_ledger.py')} --cwd {cwd} list")
    if not mine:
        return 0
    if payload.get("stop_hook_active"):
        say(f"{len(mine)} reflection(s) still pending, stop allowed because this is a "
            "forced continuation: " + ", ".join(r["agent_id"] for r in mine))
        return 0
    sys.stdout.write(json.dumps({"decision": "block", "reason": block_reason(mine, cwd)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
