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

Attribution. session_id is a common input field of every hook event (Claude
Code hooks reference), so its absence is an anomaly, never a quiet default:
  * a row recorded without a session_id belongs to no session we can name; it
    blocks (fail closed: dropping it would lose the reflection) and the reason
    says it is unattributed, never that it is this session's;
  * a Stop payload without a session_id cannot tell which rows are its own; all
    pending rows block, and the reason says the session could not be determined.

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


def block_reason(rows: list, cwd: str, caveats: tuple = ()) -> str:
    lift_tool = os.path.join(_ROOT, "tools", "reflection_ledger.py")
    shown = "\n".join(_entry_text(r, cwd, lift_tool) for r in rows[:MAX_LISTED])
    more = f"\n(+{len(rows) - MAX_LISTED} more: python3 {lift_tool} --cwd {cwd} list)" \
        if len(rows) > MAX_LISTED else ""
    return "".join(f"NOTE: {c}\n" for c in caveats) + (
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


def _attribute(reflection_ledger, everything: list, session):
    """(rows that block, caveats to report, count belonging to other sessions)."""
    if session is None:
        return everything, ([f"the Stop payload carries no session_id: cannot tell which of the "
                             f"{len(everything)} pending reflection(s) are this session's, "
                             "all of them block"] if everything else []), 0
    mine, unattributed, elsewhere = reflection_ledger.split_by_session(everything, session)
    caveats = [f"{len(unattributed)} pending reflection(s) were recorded without a session_id "
               "and are unattributed; they block until lifted"] if unattributed else []
    return mine + unattributed, caveats, len(elsewhere)


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
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else ""
    session = session or None
    try:
        path = reflection_ledger.ledger_path(cwd)
    except reflection_ledger.LedgerError:
        return 0  # not a git repository: no ledger can exist here, nothing is owed
    try:
        everything = reflection_ledger.pending(path)
    except reflection_ledger.LedgerError as exc:
        say(f"ledger unreadable, reflections NOT enforced: {exc}")
        return 0
    mine, caveats, elsewhere = _attribute(reflection_ledger, everything, session)
    for caveat in caveats:
        say(caveat)
    if elsewhere:
        say(f"{elsewhere} pending reflection(s) belong to other sessions: "
            f"python3 {os.path.join(_ROOT, 'tools', 'reflection_ledger.py')} --cwd {cwd} list")
    if not mine:
        return 0
    if payload.get("stop_hook_active"):
        say(f"{len(mine)} reflection(s) still pending, stop allowed because this is a "
            "forced continuation: " + ", ".join(r["agent_id"] for r in mine))
        return 0
    sys.stdout.write(json.dumps({"decision": "block", "reason": block_reason(mine, cwd, tuple(caveats))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
