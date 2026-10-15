#!/usr/bin/env python3
"""Operator verbs for the gate task (the status verb is tools/task.sh).

    gate_task.py requeue --kind commit|push [--repo D]        explicit, counted retry of a FAILED or stale gate task
    gate_task.py waive --tree TREE --reason TEXT [--repo D]   auditable waiver: lifts the Stop block for TREE

Both print one JSON document. Neither waits. A waiver never lets a commit through: only a green
verification of the tree does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_git as gitq  # noqa: E402
import gate_ledger as ledger  # noqa: E402
import gate_state as state  # noqa: E402


def _requeue(top: str, verb: str) -> dict:
    if verb == "commit":
        trees = state.commit_trees(top, amend=False, allow_empty=False)
        if trees is None:
            return {"error": "nothing is staged: there is no tree to requeue"}
    else:
        trees = state.push_trees(top)
    tree, base = trees
    started = state.tasks.requeue(state.KIND, tree, state.job_argv(top, verb, tree, base), top)
    return {"id": started.record["id"], "disposition": started.disposition,
            "attempt": started.record["attempt"], "state": started.record["state"]}


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="gate_task.py")
    parser.add_argument("verb", choices=("requeue", "waive"))
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--kind", choices=("commit", "push"), default="commit")
    parser.add_argument("--tree")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    repo = gitq.locate(args.repo)
    if repo is None:
        parser.error(f"{args.repo} is not inside a repository")
    if args.verb == "requeue":
        print(json.dumps(_requeue(repo.top, args.kind)))
        return 0
    if not (args.tree and gitq.TREE_RE.match(args.tree) and args.reason):
        parser.error("waive needs --tree TREE (a tree hash) and --reason TEXT")
    print(json.dumps(ledger.waive(repo.top, args.tree, args.reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
