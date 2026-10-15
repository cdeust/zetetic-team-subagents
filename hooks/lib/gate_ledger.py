"""The gate's todo for the Stop hook: verification results in the order they happened, and waivers.

Owner rule (2026-09-30): errors are added to your todo and you stop when the todo is empty. The baseline
(~/.claude/hooks/stop-gate-ledger.py) kept an append-only `failures.jsonl` next to the proofs; this module
restores its semantics on top of the task layer:

  results ledger   `gate-results.jsonl` in the task state directory. The worker appends one line
                   {"verb", "tree", "key", "rc"} when a verification ends (gate_run.main). LINE ORDER is
                   the order of events: no clock decides anything.
  open failure     a line with rc != 0 and neither
                     - a LATER line of the same verb with rc == 0 (a green verification lifts the failures
                       before it, as the baseline's later green proof did), nor
                     - a waiver for its tree (`gate_task.py waive`; auditable, lifts the Stop block only).
  at risk          tracked changes remain uncommitted (staged or not: a failed tree that was unstaged with
                   its edits left in the working copy is still your todo), or HEAD is ahead of its upstream.

A worker killed before it could append leaves no line: that is an infrastructure failure, reported to the
author by the commit hook (gate_state.failed_message), not a gate failure the Stop hook can name.
Waivers are lines of their own file, `gate-waivers.jsonl`.
"""
from __future__ import annotations

import json
import os
from typing import NamedTuple

import gate_git as gitq
import gate_paths  # noqa: F401  (puts tools/lib on sys.path for task_store)
import task_store

RESULTS = "gate-results.jsonl"
WAIVERS = "gate-waivers.jsonl"


def _results_path(top: str) -> str:
    return os.path.join(task_store.tasks_dir(top), RESULTS)


def _waiver_path(top: str) -> str:
    return os.path.join(task_store.tasks_dir(top), WAIVERS)


def _append(path: str, row: dict) -> None:
    """One O_APPEND write of one line: concurrent workers' lines never interleave."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)


class Result(NamedTuple):
    """The end of one verification: what kind of act, which tree, which task, how it ended."""
    verb: str
    tree: str
    key: str
    rc: int


def record(top: str, result: Result) -> None:
    """Append the end of a verification to the results ledger."""
    _append(_results_path(top), {**result._asdict(), "time": task_store.utc_now()})


def waive(top: str, tree: str, reason: str) -> dict:
    """Append an auditable waiver for ``tree``: it lifts the Stop block only; it never lets a commit through."""
    row = {"tree": tree, "reason": reason, "time": task_store.utc_now()}
    _append(_waiver_path(top), row)
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
            continue  # a torn or foreign line: not a record
    return [r for r in rows if isinstance(r, dict)]


def waived_trees(top: str) -> set:
    return {r["tree"] for r in _rows(_waiver_path(top)) if isinstance(r.get("tree"), str)}


def _is_pass(row: dict) -> bool:
    return row.get("rc") == 0 and not isinstance(row.get("rc"), bool)


def open_failures(top: str) -> list:
    """Result rows (rc != 0) not lifted by a later green of the same verb and not waived, in ledger order."""
    waived = waived_trees(top)
    rows = [r for r in _rows(_results_path(top)) if isinstance(r.get("verb"), str) and isinstance(r.get("tree"), str)]
    green_later: set = set()
    open_rows: list = []
    for row in reversed(rows):  # invariant: green_later holds the verbs with a green line AFTER the current row
        verb = row["verb"]
        if _is_pass(row):
            green_later.add(verb)
        elif verb not in green_later and row["tree"] not in waived:
            open_rows.append(row)
    return list(reversed(open_rows))


def work_at_risk(top: str) -> bool:
    """Tracked changes remain uncommitted, or HEAD is ahead of its upstream. Untracked files are not commit risk."""
    if gitq.tree_of(top, "HEAD") is None:
        return gitq.staged_tree(top) != gitq.empty_tree(top)
    # `git diff` (porcelain) compares content for files whose stat data is stale; plumbing `diff-index` would
    # report them as changed. GIT_OPTIONAL_LOCKS=0 (gate_git) keeps it from writing the refreshed index back.
    if gitq.git(top, "diff", "--quiet", "HEAD", "--").returncode != 0:
        return True
    return gitq.head_ahead_of_upstream(top)
