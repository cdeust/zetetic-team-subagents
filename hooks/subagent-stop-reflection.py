#!/usr/bin/env python3
"""subagent-stop-reflection.py -- SubagentStop hook: schedule a reflection.

Owner decision 2026-10-13: after each action performed by an agent, a
reflection task is scheduled so agents improve next time. This hook does the
scheduling; ``stop-reflection-gate.py`` makes it binding.

On every SubagentStop it
  (a) identifies the run (tools/reflection_subagent.py: payload fields first,
      then the sibling meta.json, every fallback reported); a run Claude Code
      spawned inside a tool (no agent-<id>.jsonl, no meta.json: the WebFetch
      summariser) is reported on stderr and gets no reflection;
  (b) appends the pending row to the per-repo ledger
      ``<git-common-dir>/zetetic-gates/reflections.jsonl``
      (tools/reflection_ledger.py) FIRST: it is the enforcement record and must
      exist before any network call can eat the hook's time budget;
  (c) retains the run into Hindsight when Hindsight is configured for the cwd
      (tools/reflection_hindsight.py, bounded by HINDSIGHT_DEADLINE_S), tagged
      agent_type:<type> and source:subagent, then appends the outcome as a
      second ledger line keyed by agent_id (the reader merges it in).

No silent fallback: every outcome, including "Hindsight not configured" and
"Hindsight server down", is written to stderr AND into the ledger row. The hook
always exits 0 (exit 2 would block the subagent from stopping); a failure is
reported, never hidden and never fatal.

Pre: stdin is the SubagentStop event JSON.
Post: stderr names the outcome of each of (a), (b), (c); the ledger holds at
most one pending row for the agent id, written before Hindsight is contacted.
A later stop of the same agent (the cycle gate blocked an earlier one) appends
its newer final message as an excerpt row, which the reader takes.
"""
from __future__ import annotations

import json
import os
import sys

_TOOL = "subagent-reflection"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))


def say(message: str) -> None:
    print(f"[{_TOOL}] {message}", file=sys.stderr)


def _record_pending(reflection_ledger, gates_jsonl, cwd: str, run):
    """Append the pending row; the ledger path, or None after reporting why not."""
    placeholder = {"status": "pending", "detail": "Hindsight retain not yet attempted "
                   "(no outcome line follows if the hook was killed or the ledger was unwritable)",
                   "bank": None, "document_id": None}
    try:
        path = reflection_ledger.ledger_path(cwd)
        added = reflection_ledger.append_pending(path, {**run.as_row(), "hindsight": placeholder})
    except gates_jsonl.LedgerError as exc:
        say(f"ledger NOT written, the Stop gate cannot enforce this reflection: {exc}")
        return None
    if added:
        verdict = "pending reflection recorded"
    elif reflection_ledger.refresh_excerpt(path, run.agent_id, run.excerpt):
        verdict = "already in the ledger, newer final message recorded"
    else:
        verdict = "already in the ledger, not duplicated"
    say(f"{verdict}: {run.agent_type} {run.agent_id} ({path})")
    return path


def main() -> int:
    try:
        import reflection_hindsight
        import gates_jsonl
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
    if run.tool_internal():
        say(f"{run.agent_id} has no agent-<id>.jsonl transcript and no meta.json: a run Claude Code "
            "spawned inside a tool (e.g. the WebFetch summariser), not a delegated agent; "
            "no reflection scheduled")
        return 0
    for note in run.notes:
        say(f"note ({run.agent_id}): {note}")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    path = _record_pending(reflection_ledger, gates_jsonl, cwd, run)
    hindsight = reflection_hindsight.retain(cwd, run.as_row())
    say(f"hindsight {hindsight.status}: {hindsight.detail}")
    if path is not None:
        try:
            reflection_ledger.record_hindsight(path, run.agent_id, hindsight.as_row())
        except gates_jsonl.LedgerError as exc:
            say(f"hindsight outcome NOT written to the ledger: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
