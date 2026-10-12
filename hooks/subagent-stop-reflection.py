#!/usr/bin/env python3
"""subagent-stop-reflection.py -- SubagentStop hook: schedule a reflection.

Owner decision 2026-10-13: after each action performed by an agent, a
reflection task is scheduled so agents improve next time. This hook does the
scheduling; ``stop-reflection-gate.py`` makes it binding.

On every SubagentStop it
  (a) identifies the run (tools/reflection_subagent.py: payload fields first,
      then the sibling meta.json, every fallback reported);
  (b) retains the run into Hindsight when Hindsight is configured for the cwd
      (tools/reflection_hindsight.py), tagged agent_type:<type> and
      source:subagent;
  (c) appends a pending row, carrying the Hindsight outcome, to the per-repo
      ledger ``<git-common-dir>/zetetic-gates/reflections.jsonl``
      (tools/reflection_ledger.py).

No silent fallback: every outcome, including "Hindsight not configured" and
"Hindsight server down", is written to stderr AND into the ledger row. The hook
always exits 0 (exit 2 would block the subagent from stopping); a failure is
reported, never hidden and never fatal.

Pre: stdin is the SubagentStop event JSON.
Post: stderr names the outcome of each of (a), (b), (c); the ledger holds at
most one row for the agent id.
"""
from __future__ import annotations

import json
import os
import sys

_TOOL = "subagent-reflection"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))


def say(message: str) -> None:
    print(f"[{_TOOL}] {message}", file=sys.stderr)


def main() -> int:
    try:
        import reflection_hindsight
        import reflection_ledger
        import reflection_subagent
    except ImportError as exc:  # FAILS_ON: tools/ not shipped beside hooks/ (partial install)
        say(f"cannot load tools/reflection_*.py, no reflection scheduled: {exc}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        say(f"stdin is not JSON, no reflection scheduled: {exc}")
        return 0
    if not isinstance(payload, dict):
        say("stdin is not a JSON object, no reflection scheduled")
        return 0
    try:
        run = reflection_subagent.resolve_run(payload)
    except reflection_subagent.RunUnidentified as exc:
        say(f"cannot identify the subagent, no reflection scheduled: {exc}")
        return 0
    for note in run.notes:
        say(f"note ({run.agent_id}): {note}")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    hindsight = reflection_hindsight.retain(cwd, run.as_row())
    say(f"hindsight {hindsight.status}: {hindsight.detail}")
    try:
        path = reflection_ledger.ledger_path(cwd)
        added = reflection_ledger.append_pending(
            path, {**run.as_row(), "hindsight": hindsight.as_row()})
    except reflection_ledger.LedgerError as exc:
        say(f"ledger NOT written, the Stop gate cannot enforce this reflection: {exc}")
        return 0
    verdict = "pending reflection recorded" if added else "already in the ledger, not duplicated"
    say(f"{verdict}: {run.agent_type} {run.agent_id} ({path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
