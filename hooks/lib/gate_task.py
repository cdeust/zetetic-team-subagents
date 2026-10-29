#!/usr/bin/env python3
"""Operator verbs for the gate task (the status verb is tools/task.sh).

    gate_task.py requeue --id ID [--repo D]                    explicit, counted retry of a FAILED or stale gate task
    gate_task.py waive --tree TREE --reason TEXT [--repo D]   auditable waiver: lifts the Stop block for TREE
    gate_task.py verify --base REV|- [--kind K] [--repo D]    verify HEAD's tree now, in the foreground (CI)

requeue and waive print one JSON document and never wait. A waiver never lets a commit through: only a green
verification of the tree does.

verify plans HEAD's tree exactly as the commit hook would (gate_state.prepare: the trusted list,
the rules and the runner of this environment) and runs the worker in the foreground, so its exit code is the
verdict. CI runs it on every change to this repository with a hook-like environment: the repository's own gate
must stay satisfiable on its own tree (.github/workflows/ci.yml, gate-self-verification).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_git as gitq  # noqa: E402
import gate_ledger as ledger  # noqa: E402
import gate_runner as runner_mod  # noqa: E402
import gate_state as state  # noqa: E402


def _requeue(top: str, tid: str) -> dict:
    """Relaunch the task ``tid`` with the command it recorded: its runner (the hook's interpreter and the checks'
    environment) travels in that command, so a requeue from a shell whose environment differs from the hook's
    retries the very verification the hook keyed, and the next commit attempt finds it."""
    rec = state.tasks.status(tid, top)
    if rec is None or rec.get("kind") != state.KIND:
        return {"error": f"no gate task {tid} in {top}"}
    started = state.tasks.requeue(state.KIND, rec["key"], rec["input"]["argv"], top)
    return {"id": started.record["id"], "disposition": started.disposition,
            "attempt": started.record["attempt"], "state": started.record["state"]}


def verify(top: str, base_rev: str, verb: str) -> int:
    """Verify HEAD's tree against ``base_rev``'s (`-`: the empty tree) in the foreground; the exit code is the verdict."""
    tree = gitq.tree_of(top, "HEAD")
    base = None if base_rev == "-" else gitq.tree_of(top, base_rev)
    if tree is None or (base_rev != "-" and base is None):
        print(f"[gate] cannot resolve HEAD and {base_rev} to trees in {top}", file=sys.stderr)
        return 2
    plan = state.prepare(top, verb, tree, base)
    if isinstance(plan, state.Verdict):
        print(plan.message or "[gate] this tree declares no gate: nothing to verify")
        return 0 if plan.allow else 1
    print(f"[gate] verifying {tree} against {base or 'the empty tree'}: task {plan.id}; "
          f"{runner_mod.describe(plan.runner)}", flush=True)
    return subprocess.run(plan.argv, cwd=top, stdin=subprocess.DEVNULL, check=False).returncode


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="gate_task.py")
    parser.add_argument("verb", choices=("requeue", "waive", "verify"))
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--kind", choices=("commit", "push"), default="commit")
    parser.add_argument("--tree")
    parser.add_argument("--reason")
    parser.add_argument("--id")
    parser.add_argument("--base")
    args = parser.parse_args(argv)
    repo = gitq.locate(args.repo)
    if repo is None:
        parser.error(f"{args.repo} is not inside a repository")
    if args.verb == "requeue":
        if not args.id:
            parser.error("requeue needs --id ID (the task id the failure names)")
        print(json.dumps(_requeue(repo.top, args.id)))
        return 0
    if args.verb == "verify":
        if not args.base:
            parser.error("verify needs --base REV (the commit the change is measured from) or - (the empty tree)")
        return verify(repo.top, args.base, args.kind)
    if not (args.tree and gitq.TREE_RE.match(args.tree) and args.reason):
        parser.error("waive needs --tree TREE (a tree hash) and --reason TEXT")
    print(json.dumps(ledger.waive(repo.top, args.tree, args.reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
