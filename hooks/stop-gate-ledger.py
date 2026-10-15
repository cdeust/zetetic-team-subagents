#!/usr/bin/env python3
"""Stop hook: do not stop while the gate ledger has an open failure and work remains at risk.

Owner rule (2026-09-30): errors are added to your todo and you stop when the todo is empty. The todo is the
set of OPEN failures of the results ledger (hooks/lib/gate_ledger.py): a verification that ended red and
was neither lifted by a later green of the same kind nor waived. It blocks while work is at risk: tracked
changes remain uncommitted (staged or not, so a failed tree that was unstaged with its edits left in the
working copy still blocks), or HEAD is ahead of its upstream. A running verification is not a failure and
never blocks. A repo that declares no gate (in HEAD's tree, gate_rules) is out of scope.

Repatriated from ~/.claude/hooks/stop-gate-ledger.py, with the baseline's semantics: failures are lifted by
LINE ORDER of an append-only ledger, never by a clock, and the 8 s git kill is gone (no timer anywhere).
Read-only. Never raises: any error exits 0 silently (a Stop hook must not fail hard).
Protocol: stdout {"decision":"block","reason":...}; payload has stop_hook_active.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import gate_git as gitq  # noqa: E402
import gate_ledger as ledger  # noqa: E402
import gate_rules as rules  # noqa: E402
import gate_state as state  # noqa: E402

_MAX_LISTED = 5  # source: ~/.claude/hooks/stop-gate-ledger.py (_MAX_LISTED = 5), the baseline this hook restores


def _line(top: str, row: dict) -> str:
    output = (state.record_of_key(top, row["key"]) or {}).get("output_path")
    return (f"- {row['verb']} tree {row['tree']} (rc={row.get('rc')}): output {output}; status: "
            f"{state.status_command(top, row['key'])}; fix and restage, or waive: "
            f"python3 {state.CLI} waive --repo {top} --tree {row['tree']} --reason \"...\"")


def decide(payload: dict) -> dict | None:
    # stop_hook_active: one-shot nudge only; the auditable way out of a failure that cannot be fixed is the waiver.
    if payload.get("stop_hook_active"):
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    repo = gitq.locate(cwd)
    if repo is None or not rules.declared(repo.top):
        return None
    failures = ledger.open_failures(repo.top)
    if not failures or not ledger.work_at_risk(repo.top):
        return None
    lines = [_line(repo.top, row) for row in failures[:_MAX_LISTED]]
    more = f"\n(+{len(failures) - _MAX_LISTED} more)" if len(failures) > _MAX_LISTED else ""
    reason = ("Your todo is not empty: a gate verification failed and tracked changes remain uncommitted or "
              "unpushed. Fix it (a later green verification of the same kind lifts the failure) or waive it "
              "auditably.\n" + "\n".join(lines) + more)
    return {"decision": "block", "reason": reason}


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            return 0
        result = decide(payload)
        if result:
            print(json.dumps(result))
    except Exception:  # FAILS_ON: anything; a Stop hook must never fail hard or loop the session.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
