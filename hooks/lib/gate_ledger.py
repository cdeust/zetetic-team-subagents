"""What the Stop hook needs: which trees at risk have a FAILED, unwaived gate verification.

Reads task records (``gate-<tree>``) and the waiver file only. The "work at risk" trees are the staged
tree (when it differs from HEAD's) and HEAD's tree (when HEAD is ahead of its upstream): a failure of
any other tree is history, not a todo. Unstaged edits are not at risk here by construction: no command
in this module reads the working tree, so a Stop hook cannot hang on a huge checkout.
"""
from __future__ import annotations

import json
import os

import gate_git as gitq
import gate_state as state
import task_store

WAIVERS = "gate-waivers.jsonl"


def _waiver_path(top: str) -> str:
    return os.path.join(task_store.tasks_dir(top), WAIVERS)


def waive(top: str, tree: str, reason: str) -> dict:
    """Append an auditable waiver for ``tree``: it lifts the Stop block only; it never lets a commit through."""
    row = {"tree": tree, "reason": reason, "time": task_store.utc_now()}
    with open(_waiver_path(top), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def _rows(path: str) -> list:
    """The JSON objects of a jsonl file; a malformed line is skipped, it never hides the lines around it."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a torn or foreign line: not a waiver
    return [r for r in rows if isinstance(r, dict)]


def waived_trees(top: str) -> set:
    return {r["tree"] for r in _rows(_waiver_path(top)) if isinstance(r.get("tree"), str)}


def trees_at_risk(top: str) -> list:
    staged, head = gitq.staged_tree(top), gitq.tree_of(top, "HEAD")
    at_risk = []
    if staged != (head or gitq.empty_tree(top)):
        at_risk.append(staged)
    if head and gitq.head_ahead_of_upstream(top):
        at_risk.append(head)
    return at_risk


def open_failures(top: str) -> list:
    """Records (state `failed`, not waived) of the trees at risk."""
    waived = waived_trees(top)
    found = []
    for tree in trees_at_risk(top):
        rec = state.peek(top, tree)
        if rec is not None and rec["state"] == "failed" and tree not in waived:
            found.append(rec)
    return found
