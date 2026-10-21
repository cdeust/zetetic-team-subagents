#!/usr/bin/env python3
"""reflection_ledger.py -- the pending-reflection ledger and its lift command.

Owner decision 2026-10-13: after each action performed by an agent, a
reflection task is scheduled so agents improve next time. This module is the
mechanism behind that decision. ``hooks/subagent-stop-reflection.py`` appends a
pending row when a subagent stops; ``hooks/stop-reflection-gate.py`` refuses to
let the session stop while a row is pending; the ``lift`` command below
is the only way to clear a row, and it demands the Cortex memory id that holds
the lesson as evidence.

Ledger contract (``gates_jsonl.py``, same family as the gate failure ledger
``failures.jsonl`` written by ``scripts/gate.sh``):
  * append-only JSON lines, one file per repository, under
    ``<git-common-dir>/zetetic-gates/``. The file is ``reflections.jsonl``, a
    sibling of ``failures.jsonl``: a failure is lifted by a green proof, a
    reflection only by a stored lesson, so the two never share rows.
  * a pending row is {"agent_id", "agent_type", "description",
    "transcript_path", "session_id", "excerpt", "notes", "time"}.
  * an excerpt row is {"excerpt_for": <agent_id>, "excerpt": ..., "time": ...}:
    a later SubagentStop of the same agent (the cycle gate blocked an earlier
    one, so the agent worked on) carries a newer final message; the reader
    merges the latest one into the pending row's ``excerpt``.
  * a lift row is {"lift": <agent_id>, "memory_id": <int>, "time": ...}, the
    analogue of the waiver row ``{"waive": <gate>, ...}``.
  * a row is pending when no lift row names its agent_id. A row of any other
    shape (no ``agent_id``) is never pending: the Hindsight outcome rows
    {"hindsight_for": ...} that release 2.43.0 wrote stay in old ledgers and
    are ignored with the rest.

Pre: ``cwd`` is a directory inside a git work tree for any operation.
Post: the file only ever grows by whole lines; no row is rewritten.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

from gates_jsonl import LedgerError, now_iso, read_rows
from gates_jsonl import append_row
from gates_jsonl import ledger_path as _ledger_path

LEDGER_NAME = "reflections.jsonl"


class LiftRefused(Exception):
    """A lift request that does not meet the evidence contract."""


def ledger_path(cwd: str) -> str:
    """Absolute ledger path for the repository containing ``cwd``.

    Pre: none. Post: returns the path, or raises LedgerError naming why not.
    """
    return _ledger_path(cwd, LEDGER_NAME)


def append_pending(path: str, entry: Dict) -> bool:
    """Record a pending reflection. False when this agent_id is already in the
    ledger (SubagentStop can fire twice for one subagent); True when appended.

    Pre: ``entry`` has a non-empty ``agent_id``. Post: at most one pending row
    per agent_id exists, whatever the number of calls.
    """
    agent_id = entry.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise LedgerError("a pending entry needs a non-empty agent_id")
    if any(r.get("agent_id") == agent_id for r in read_rows(path)):
        return False
    append_row(path, {**entry, "time": now_iso()})
    return True


def _latest_excerpts(rows: List[Dict]) -> Dict[str, str]:
    """agent_id -> the excerpt of its latest row (pending or excerpt_for)."""
    out: Dict[str, str] = {}
    for r in rows:
        if isinstance(r.get("excerpt_for"), str):
            out[r["excerpt_for"]] = r.get("excerpt") or ""
        elif isinstance(r.get("agent_id"), str) and "lift" not in r:
            out.setdefault(r["agent_id"], r.get("excerpt") or "")
    return out


def refresh_excerpt(path: str, agent_id: str, excerpt: str) -> bool:
    """Append an excerpt row when ``excerpt`` differs from the latest one
    recorded for ``agent_id``; True when appended.

    Pre: the pending row for ``agent_id`` exists. Post: rows are only appended."""
    if not excerpt or _latest_excerpts(read_rows(path)).get(agent_id) == excerpt:
        return False
    append_row(path, {"excerpt_for": agent_id, "excerpt": excerpt, "time": now_iso()})
    return True


def _lifted_ids(rows: List[Dict]) -> set:
    return {r["lift"] for r in rows if isinstance(r.get("lift"), str)}


def pending(path: str, session_id: Optional[str] = None) -> List[Dict]:
    """Pending rows, oldest first; restricted to one session when given."""
    rows = read_rows(path)
    lifted, excerpts = _lifted_ids(rows), _latest_excerpts(rows)
    return [{**r, "excerpt": excerpts.get(r["agent_id"], r.get("excerpt"))}
            for r in rows
            if "lift" not in r
            and isinstance(r.get("agent_id"), str) and r["agent_id"] not in lifted
            and (session_id is None or r.get("session_id") == session_id)]


def split_by_session(rows: List[Dict], session_id: str):
    """(mine, unattributed, elsewhere): rows of ``session_id``, rows recorded
    without any session_id, and rows of other sessions. A row with no session
    id is never assigned to a session it cannot be shown to belong to."""
    mine = [r for r in rows if r.get("session_id") == session_id]
    unattributed = [r for r in rows if not r.get("session_id")]
    elsewhere = [r for r in rows if r.get("session_id") and r.get("session_id") != session_id]
    return mine, unattributed, elsewhere


def lift(path: str, agent_id: str, memory_id: object) -> Dict:
    """Mark a pending reflection done, with the Cortex memory id as evidence.

    Pre: ``agent_id`` names a pending row; ``memory_id`` is a positive integer
    (the id Cortex ``remember`` returned). Post: a lift row is appended and
    returned. Refuses (LiftRefused) without evidence, on an unknown agent id,
    or on one already lifted; the ledger is unchanged in every refusal.
    """
    if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id <= 0:
        raise LiftRefused(
            "refusing to lift without evidence: pass --memory-id <positive integer>, "
            "the id Cortex `remember` returned for the lesson-candidate memory")
    rows = read_rows(path)
    if agent_id in _lifted_ids(rows):
        raise LiftRefused(f"reflection for {agent_id} is already lifted")
    if not any(r.get("agent_id") == agent_id and "lift" not in r for r in rows):
        raise LiftRefused(f"no pending reflection for agent {agent_id} in {path}")
    row = {"lift": agent_id, "memory_id": memory_id, "time": now_iso()}
    append_row(path, row)
    return row


def _to_int(text: str) -> Optional[int]:
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reflection_ledger.py",
        description="List or lift pending subagent reflections.")
    parser.add_argument("--cwd", default=os.getcwd(),
                        help="directory inside the repository whose ledger to use")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print the pending reflections")
    lift_p = sub.add_parser("lift", help="mark a reflection done")
    lift_p.add_argument("agent_id")
    lift_p.add_argument("--memory-id", default=None,
                        help="Cortex memory id of the lesson-candidate memory (required)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        path = ledger_path(args.cwd)
        if args.command == "list":
            for row in pending(path):
                print(f"{row['agent_id']}\t{row.get('agent_type', '?')}\t"
                      f"{row.get('description', '')}")
            return 0
        memory_id = _to_int(args.memory_id) if args.memory_id is not None else None
        row = lift(path, args.agent_id, memory_id)
    except (LedgerError, LiftRefused) as exc:
        print(f"[reflection-ledger] {exc}", file=sys.stderr)
        return 2
    print(f"lifted {row['lift']} with Cortex memory {row['memory_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
