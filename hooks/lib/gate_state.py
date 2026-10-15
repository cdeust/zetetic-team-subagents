"""The gate's verdict on a tree, read from (and started in) the async task `gate-<tree>`.

The decision is a function of the task record alone (docs/async-tasks.md, docs/gate.md); nothing here
waits, sleeps, or compares elapsed time:

  disposition  record                  verdict
  cached       done, rc 0              allow (the cached proof; push reuses the commit's)
  failed       failed                  deny, naming the output file
  started      queued (just launched)  deny: verification started, retry when it finishes
  in-flight    queued/running, alive   deny: verification running, retry when it finishes
  stale        in flight, worker dead  requeue once (explicit, counted), then as `started`

``check`` is the only entry that starts a task; ``peek`` only reads.
"""
from __future__ import annotations

import os
import sys
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "tools", "lib"))
sys.path.insert(0, HERE)
import gate_git as gitq  # noqa: E402
import tasks  # noqa: E402
import task_store  # noqa: E402

KIND = "gate"
RUN = os.path.join(HERE, "gate_run.py")
CLI = os.path.join(HERE, "gate_task.py")
TASK_SH = os.path.join(PLUGIN_ROOT, "tools", "task.sh")
_TAIL_LINES = 12  # source: enough of the failing check's output to see the assertion without opening the file


class Verdict(NamedTuple):
    allow: bool
    message: str


def commit_trees(top: str, amend: bool, allow_empty: bool) -> tuple[str, str | None] | None:
    """(tree, base) of the commit about to be made, or None when it would be refused anyway (empty index)."""
    tree, head = gitq.staged_tree(top), gitq.tree_of(top, "HEAD")
    if not (amend or allow_empty) and tree == (head or gitq.empty_tree(top)):
        return None
    return tree, (gitq.tree_of(top, "HEAD^") if amend else head)


def push_trees(top: str) -> tuple[str, str | None]:
    """(tree, base) of what a push publishes: HEAD's tree, measured from its parent."""
    tree = gitq.tree_of(top, "HEAD")
    if tree is None:
        raise gitq.Unavailable("cannot compute the tree of HEAD (no commit yet?)")
    return tree, gitq.tree_of(top, "HEAD^")


def task_id(tree: str) -> str:
    return task_store.task_id(KIND, tree)


def job_argv(top: str, verb: str, tree: str, base: str | None) -> list:
    """The command the worker runs. ``verb`` is `commit` or `push`; ``base`` is the tree the change is measured from."""
    return [sys.executable, "-B", RUN, "run", "--repo", top, "--tree", tree, "--base", base or "-", "--kind", verb]


def _status_cmd(top: str, tid: str) -> str:
    return f"{TASK_SH} status {tid} --repo {top}"


def _tail(rec: dict) -> str:
    lines = (rec.get("result_excerpt") or "").strip().splitlines()[-_TAIL_LINES:]
    return "\n".join("    " + line for line in lines)


def failed_message(top: str, rec: dict) -> str:
    cause = rec.get("reason") or f"rc={rec.get('rc')}" + (f", signal {rec['signal']}" if rec.get("signal") else "")
    return (f"GATE-PROOF: verification FAILED for tree {rec['key']} ({cause}).\n"
            f"Output: {rec.get('output_path')}\n{_tail(rec)}\n"
            f"Fix the cause and restage (a different tree starts a new verification). After an "
            f"infrastructure failure only: python3 {CLI} requeue --repo {top} --kind <commit|push>")


def pending_message(top: str, rec: dict, started: bool) -> str:
    what = "started" if started else "running"
    return (f"GATE-PROOF: verification {what} for tree {rec['key']}; retry the commit when it finishes "
            f"(status: {_status_cmd(top, rec['id'])}). This hook does not wait.")


def _requeue_stale(top: str, tree: str, argv: list) -> Verdict:
    again = tasks.requeue(KIND, tree, argv, top)
    if again.disposition == "orphaned":
        return Verdict(False, (f"GATE-PROOF: the verification worker for tree {tree} died while its command "
                               f"is still running (process group {again.record.get('pgid')}); inspect with "
                               f"{_status_cmd(top, again.record['id'])} and see docs/async-tasks.md (orphaned)."))
    return Verdict(False, pending_message(top, again.record, started=True) +
                   f" (attempt {again.record['attempt']}: the previous worker died without a result)")


def verdict_of(top: str, tree: str, started: tasks.Started, argv: list) -> Verdict:
    rec, disp = started.record, started.disposition
    if disp == "cached":
        return Verdict(True, "")
    if disp == "failed":
        return Verdict(False, failed_message(top, rec))
    if disp == "stale":
        return _requeue_stale(top, tree, argv)
    return Verdict(False, pending_message(top, rec, started=disp == "started"))


def check(top: str, verb: str, tree: str, base: str | None) -> Verdict:
    """Start-or-find the task for ``tree`` and judge it. Returns at once, whatever the task is doing."""
    argv = job_argv(top, verb, tree, base)
    return verdict_of(top, tree, tasks.start(KIND, tree, argv, top), argv)


def begin(top: str, verb: str, tree: str, base: str | None) -> tasks.Started:
    """Start-or-find the task without judging it (the PostToolUse head start)."""
    return tasks.start(KIND, tree, job_argv(top, verb, tree, base), top)


def peek(top: str, tree: str) -> dict | None:
    """The record of `gate-<tree>` or None. Reads only."""
    return tasks.status(task_id(tree), top)
