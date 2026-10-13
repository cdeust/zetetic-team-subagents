#!/usr/bin/env python3
"""reflection_ledger.py -- the pending-reflection ledger and its lift command.

Owner decision 2026-10-13: after each action performed by an agent, a
reflection task is scheduled so agents improve next time. This module is the
mechanism behind that decision. ``hooks/subagent-stop-reflection.py`` appends a
pending row when a subagent stops; ``hooks/stop-reflection-gate.py`` refuses to
let the orchestrator stop while a row is pending; the ``lift`` command below
is the only way to clear a row, and it demands the Cortex memory id that holds
the lesson as evidence.

Ledger contract (same family as the gate failure ledger ``failures.jsonl``,
written by ``scripts/gate.sh`` and read by the user-level stop-gate-ledger):
  * append-only JSON lines, one file per repository, under
    ``<git-common-dir>/zetetic-gates/``. The file is ``reflections.jsonl``, a
    sibling of ``failures.jsonl``: a failure is lifted by a green proof, a
    reflection only by a stored lesson, so the two never share rows.
  * a pending row is {"agent_id", "agent_type", "description",
    "transcript_path", "session_id", "excerpt", "hindsight", "notes", "time"}.
  * a hindsight row is {"hindsight_for": <agent_id>, "hindsight": {...}, "time": ...}:
    the outcome of the network retain, appended AFTER the pending row (the
    pending row is the enforcement record and must not wait on the network).
    The reader merges the latest one into the pending row's ``hindsight``.
  * a lift row is {"lift": <agent_id>, "memory_id": <int>, "time": ...}, the
    analogue of the waiver row ``{"waive": <gate>, ...}``.
  * a row is pending when no lift row names its agent_id.

Pre: ``cwd`` is a directory inside a git work tree for any operation.
Post: the file only ever grows by whole lines; no row is rewritten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

LEDGER_DIR = "zetetic-gates"
LEDGER_NAME = "reflections.jsonl"
# Rows carry an excerpt of the subagent transcript, which Claude Code writes
# owner-only; the ledger must not be wider. source: ls -l ~/.claude/projects/*/*.jsonl
# (-rw-------) and CodeQL py/overly-permissive-file alert #45 on PR #153.
LEDGER_FILE_MODE = 0o600
# One git rev-parse is local and instant; the bound only stops a wedged git
# from wedging the hook. source: stop-gate-ledger.py _GIT_TIMEOUT (8 s).
GIT_TIMEOUT_S = 8


class LedgerError(Exception):
    """The ledger cannot be located or written; the caller must report it."""


class LiftRefused(Exception):
    """A lift request that does not meet the evidence contract."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def ledger_path(cwd: str) -> str:
    """Absolute ledger path for the repository containing ``cwd``.

    Pre: none. Post: returns the path, or raises LedgerError naming why not.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=cwd, capture_output=True,
            text=True, timeout=GIT_TIMEOUT_S, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerError(f"git could not be run in {cwd!r}: {exc}") from exc
    common = proc.stdout.strip()
    if proc.returncode != 0 or not common:
        raise LedgerError(f"{cwd!r} is not inside a git repository: {proc.stderr.strip()}")
    base = os.path.normpath(os.path.join(cwd, common))
    return os.path.join(base, LEDGER_DIR, LEDGER_NAME)


def _parse_row(line: bytes) -> Optional[Dict]:
    """The JSON object on this line, or None for a torn, undecodable or
    non-object line."""
    try:
        row = json.loads(line.decode("utf-8"))
    except ValueError:  # includes UnicodeDecodeError
        return None  # a torn line is skipped, never allowed to hide the rest
    return row if isinstance(row, dict) else None


def read_rows(path: str) -> List[Dict]:
    """Every well-formed JSON object row; an absent file is an empty ledger."""
    try:
        with open(path, "rb") as fh:
            parsed = [_parse_row(line) for line in fh]
    except FileNotFoundError:
        return []
    except OSError as exc:  # FAILS_ON: ledger unreadable (permissions, a directory at the path)
        raise LedgerError(f"cannot read the ledger {path}: {exc}") from exc
    return [row for row in parsed if row is not None]


def _append(path: str, row: Dict) -> None:
    """Append one whole line with a single write (O_APPEND keeps concurrent
    hook processes from interleaving inside a line)."""
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, LEDGER_FILE_MODE)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        raise LedgerError(f"cannot append to {path}: {exc}") from exc


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
    _append(path, {**entry, "time": now_iso()})
    return True


def record_hindsight(path: str, agent_id: str, outcome: Dict) -> None:
    """Append the Hindsight outcome for an already-recorded pending row.

    Pre: the pending row for ``agent_id`` was appended first. Post: one whole
    line is added; the pending row is untouched, the reader merges this in.
    """
    _append(path, {"hindsight_for": agent_id, "hindsight": outcome, "time": now_iso()})


def _hindsight_outcomes(rows: List[Dict]) -> Dict[str, Dict]:
    """agent_id -> latest recorded outcome (a later line wins)."""
    return {r["hindsight_for"]: r["hindsight"] for r in rows
            if isinstance(r.get("hindsight_for"), str) and isinstance(r.get("hindsight"), dict)}


def _lifted_ids(rows: List[Dict]) -> set:
    return {r["lift"] for r in rows if isinstance(r.get("lift"), str)}


def pending(path: str, session_id: Optional[str] = None) -> List[Dict]:
    """Pending rows, oldest first; restricted to one session when given."""
    rows = read_rows(path)
    lifted, outcomes = _lifted_ids(rows), _hindsight_outcomes(rows)
    return [{**r, "hindsight": outcomes.get(r["agent_id"], r.get("hindsight"))}
            for r in rows
            if "lift" not in r and "hindsight_for" not in r
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
    _append(path, row)
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
