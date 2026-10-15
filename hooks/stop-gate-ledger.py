#!/usr/bin/env python3
"""Stop hook: do not stop while a tree you would commit, or have committed, failed its gate verification.

Owner rule (2026-09-30): errors are added to your todo and you stop when the todo is empty. The todo is
the set of FAILED `gate-<tree>` task records (tools/lib/tasks.py) of the trees at risk: the staged tree,
and HEAD's tree while HEAD is ahead of its upstream (hooks/lib/gate_ledger.py). A running verification is
not a failure and never blocks. A repo that declares no gate is out of scope.

Repatriated from ~/.claude/hooks/stop-gate-ledger.py. Changed: failures are task records, not
failures.jsonl lines, so a later green verification of the same tree lifts a failure by replacing the
record; and no repository call scans the working tree (the old `status --porcelain` was killed at 8 s).
Read-only. Never raises: any error exits 0 silently (a Stop hook must not fail hard).
Protocol: stdout {"decision":"block","reason":...}; payload has stop_hook_active.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import gate_config as config  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_ledger as ledger  # noqa: E402
import gate_state as state  # noqa: E402

_MAX_LISTED = 5


def _line(top: str, rec: dict) -> str:
    return (f"- tree {rec['key']} (rc={rec.get('rc')}): see {rec.get('output_path')}; fix and restage, or "
            f"waive: python3 {state.CLI} waive --repo {top} --tree {rec['key']} --reason \"...\"")


def decide(payload: dict) -> dict | None:
    # stop_hook_active: one-shot nudge only; the auditable way out of a failure that cannot be fixed is the waiver.
    if payload.get("stop_hook_active"):
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    repo = gitq.locate(cwd)
    if repo is None or config.declaration(repo.top) is None:
        return None
    failures = ledger.open_failures(repo.top)
    if not failures:
        return None
    lines = [_line(repo.top, rec) for rec in failures[:_MAX_LISTED]]
    more = f"\n(+{len(failures) - _MAX_LISTED} more)" if len(failures) > _MAX_LISTED else ""
    reason = ("Your todo is not empty: a tree you would commit or have not pushed failed its gate "
              "verification. Fix it (a green verification of a new tree replaces the failure) or waive it "
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
