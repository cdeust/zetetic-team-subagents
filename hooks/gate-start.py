#!/usr/bin/env python3
"""PostToolUse (Bash): start verifying the staged tree as soon as `git add|rm|mv|...` has staged it.

The head start is the point of the async gate: the verification of tree T runs while the agent writes the
commit message, so `git commit` usually finds it done. Idempotent (task `gate-commit-<tree>-<rules>-<runner>` is created
once per key, hooks/lib/gate_state.begin), returns at once, and NEVER blocks: PostToolUse cannot refuse anything
and the commit hook (gate-proof.py) starts the task itself if this one did not. A repository that is not in the
user's trusted list (hooks/lib/gate_trust.py) gets no head start: nothing it declares runs. Any failure here is
reported on stderr and costs only the head start.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import gate_actions as actions  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_state as state  # noqa: E402


def start_for(directory: str) -> str | None:
    """Start the task for the tree staged in ``directory``'s repository. Returns the disposition, or None
    (not a repository, not gated, nothing staged, or the repository is not trusted: nothing may run)."""
    if not os.path.isdir(directory):
        return None
    repo = gitq.locate(directory)
    if repo is None:
        return None
    tree, head = gitq.staged_tree(repo.top), gitq.tree_of(repo.top, "HEAD")
    if tree == (head or gitq.empty_tree(repo.top)):
        return None  # nothing staged
    started = state.begin(repo.top, "commit", tree, head)
    return None if started is None else started.disposition


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        command = (event.get("tool_input") or {}).get("command") or ""
        if event.get("tool_name") not in (None, "Bash") or "git" not in command:
            return 0
        base = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
        directories = dict.fromkeys(a["dir"] for a in actions.actions(command, base) if a["kind"] == "stage")
        for directory in directories:
            start_for(directory)
    except Exception as exc:  # FAILS_ON: anything; the head start is optional, gate-proof.py is the guard
        print(f"gate-start: no head start ({exc.__class__.__name__}: {exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
