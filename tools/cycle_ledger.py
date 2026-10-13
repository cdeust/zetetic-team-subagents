#!/usr/bin/env python3
"""cycle_ledger.py -- the per-task engineering-cycle ledger.

Owner decisions 2026-10-13 (Cortex memory cycle-ledger-pr2-decisions): every task
that changes code runs the stages of ``commands/zetetic/engineering-loop.md`` and
proves each one. A task OPENS at the first Edit/Write on a file of a git work
tree that git does not ignore (``hooks/post-edit-cycle-open.py``); it CLOSES when
``hooks/stop-cycle-gate.py`` finds every stage proven, and until then that gate
blocks the agent that opened it. Turns that change nothing cost nothing.

"A file git does not ignore" reads the owner's "tracked file": a file created by
Write is never in ``git ls-files`` when it is written, so the literal reading
would let a task made only of new files escape the gate.

Evidence is hybrid. The transcript proves what a tool call proves (recall,
Read/Grep, the edit, the check command, a review, remember: ``cycle_evidence.py``).
The rest is DECLARED here with a checkable reference: the check command
(stage 0, then matched against a green run of it in the transcript), a commit
sha resolvable in the repository, a GitHub pull-request or issue URL, or a
positive Cortex memory id. Only the benchmark may be declared not applicable,
with the reason recorded.

Rows (``gates_jsonl.py`` contract, file ``cycles.jsonl``):
  open    {"open": id, "session_id", "agent_id", "agent_type", "transcript_path",
           "window_start", "repo", "first_path", "time"}
  declare {"declare": id, "stage", "kind", "ref", "time"}       (a later one wins)
  close   {"close": id, "evidence": {stage: {"source", "detail"}},
           "counts": {"edits", "reviews", "reopens"}, "window_end",
           "transcript_path" (the one scanned), "time"}
           plus "bypass": true and "missing": [stage...] when the emergency
           switch let an unproven task through: a bypass closes the task, so it
           is logged once, not on every later stop.
A task is open while no close row names it. ``agent_id`` is null for the main
agent; one open task per (session, agent) at a time, enforced by reading and
appending under ``gates_jsonl.locked`` (parallel edits fire parallel hooks).

Pre-registered metric (two weeks before vs after), computed by ``metrics``:
  promise rate(agent_type) = stages closed on a declaration
                             / stages closed (declaration + transcript)
  reopen count(agent_type) = sum of "reopens": reviews followed by another edit.
A bypassed close counts only as a bypass: it proved nothing, so it enters
neither the promise rate nor the task and reopen counts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from typing import Dict, Iterable, List, Optional

from gates_jsonl import LedgerError, append_row, git, ledger_path as _ledger_path, locked, now_iso, read_rows

LEDGER_NAME = "cycles.jsonl"
# Stages a declaration may prove, with the reference kinds each accepts.
# source: owner decision 4 (2026-10-13): "a declaration with a checkable ref
# (sha, PR URL, memory id)"; the check is a command by engineering-loop step 0.
DECLARABLE = {"check": ("command",), "refine": ("sha", "url", "memory"),
              "benchmark": ("sha", "url", "memory", "n/a")}
_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/(pull|issues)/\d+/?$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
MAIN_AGENT = "main"


class DeclareRefused(Exception):
    """A declaration that does not meet the evidence contract."""


def ledger_path(cwd: str) -> str:
    return _ledger_path(cwd, LEDGER_NAME)


def _toplevel(directory: str) -> Optional[str]:
    """Top level of the work tree holding ``directory`` (walking up to the
    nearest existing ancestor: Write may target a directory not yet created),
    else None."""
    while not os.path.isdir(directory):
        parent = os.path.dirname(directory)
        if parent == directory:
            return None  # no ancestor exists at all
        directory = parent
    top = git(directory, "rev-parse", "--show-toplevel")
    return top.stdout.strip() if top.returncode == 0 and top.stdout.strip() else None


def task_repos(paths: Iterable[str]) -> Dict[str, Optional[str]]:
    """path -> top level of its work tree when git does not ignore it, else
    None (outside any repository, or ignored). One rev-parse per distinct
    directory and one ``check-ignore --stdin`` per work tree. Raises LedgerError
    when git cannot answer (check-ignore exits 0 when a path is ignored, 1 when
    none is, anything else is an error: git-check-ignore(1) EXIT STATUS)."""
    absolute = {p: os.path.abspath(p) for p in paths}
    tops: Dict[str, Optional[str]] = {}
    for full in absolute.values():
        directory = os.path.dirname(full)
        if directory not in tops:
            tops[directory] = _toplevel(directory)
    by_top: Dict[str, List[str]] = {}
    for full in set(absolute.values()):
        top = tops[os.path.dirname(full)]
        if top is not None:
            by_top.setdefault(top, []).append(full)
    ignored = set()
    for top, members in by_top.items():
        proc = git(top, "check-ignore", "--stdin", "-z", stdin="".join(m + "\0" for m in members))
        if proc.returncode not in (0, 1):
            raise LedgerError(f"git check-ignore failed in {top} (exit {proc.returncode}): {proc.stderr.strip()}")
        ignored.update(x for x in proc.stdout.split("\0") if x)
    return {p: None if full in ignored else tops[os.path.dirname(full)] for p, full in absolute.items()}


def task_repo(file_path: str) -> Optional[str]:
    """``task_repos`` for one path."""
    return task_repos([file_path])[file_path]


def _closed_ids(rows: List[Dict]) -> set:
    return {r["close"] for r in rows if isinstance(r.get("close"), str)}


def open_tasks(rows: List[Dict], key: Optional[tuple] = None) -> List[Dict]:
    """Open tasks whose (session_id, agent_id) equals ``key``; every open task
    when ``key`` is None. A null session_id is a value like any other here."""
    closed = _closed_ids(rows)
    return [r for r in rows if isinstance(r.get("open"), str) and r["open"] not in closed
            and (key is None or (r.get("session_id"), r.get("agent_id")) == key)]


def _window_start(rows: List[Dict], opener: Dict) -> int:
    """Where the previous closed task of the same reader stopped reading, so a
    stage proven for it is not counted again; 0 for a fresh one.

    A subagent's tool events carry the PARENT transcript_path (only SubagentStop
    names the subagent's own file), so a subagent task follows the closes of
    its agent_id (one transcript per agent_id; a second task happens when the
    subagent is resumed). A main-agent task follows the closes of main-agent
    tasks on the transcript the gate actually scanned, recorded on the close."""
    by_id = {r["open"]: r for r in rows if isinstance(r.get("open"), str)}
    agent_id = opener.get("agent_id")

    def same_reader(close_row: Dict) -> bool:
        task = by_id.get(close_row["close"], {})
        if agent_id:
            return task.get("agent_id") == agent_id
        return task.get("agent_id") is None and close_row.get("transcript_path") == opener["transcript_path"]
    return max((r.get("window_end", 0) for r in rows if isinstance(r.get("close"), str) and same_reader(r)),
               default=0)


def open_task(path: str, opener: Dict) -> tuple:
    """(task row, created): the open task of the opener's (session, agent), or a
    new one. Pre: ``opener`` has session_id, agent_id, agent_type,
    transcript_path, repo, first_path."""
    with locked(path):
        rows = read_rows(path)
        current = open_tasks(rows, (opener["session_id"], opener["agent_id"]))
        if current:
            return current[0], False
        row = {"open": uuid.uuid4().hex[:12], **opener,
               "window_start": _window_start(rows, opener), "time": now_iso()}
        append_row(path, row)
    return row, True


def declarations(rows: List[Dict], task_id: str) -> Dict[str, Dict]:
    """stage -> latest declaration row for ``task_id``."""
    return {r["stage"]: r for r in rows if r.get("declare") == task_id and r.get("stage") in DECLARABLE}


def _kind_and_ref(cwd: str, stage: str, ref: Dict) -> tuple:
    """The single (kind, value) given, checked; DeclareRefused otherwise."""
    given = [(k, v) for k, v in ref.items() if v not in (None, "")]
    if len(given) != 1:
        raise DeclareRefused("give exactly one of --command, --sha, --url, --memory-id, --not-applicable")
    kind, value = given[0]
    if kind not in DECLARABLE[stage]:
        raise DeclareRefused(f"stage {stage} accepts {', '.join(DECLARABLE[stage])}, not {kind}")
    if kind == "sha" and not (_SHA.match(value) and git(cwd, "cat-file", "-e", f"{value}^{{commit}}").returncode == 0):
        raise DeclareRefused(f"{value!r} is not a commit of the repository at {cwd}")
    if kind == "url" and not _URL.match(value):
        raise DeclareRefused(f"{value!r} is not a GitHub pull-request or issue URL")
    if kind == "memory" and not (isinstance(value, int) and not isinstance(value, bool) and value > 0):
        raise DeclareRefused("--memory-id must be the positive integer Cortex `remember` returned")
    return kind, value.strip() if isinstance(value, str) else value


def declare(cwd: str, task_id: str, stage: str, ref: Dict) -> Dict:
    """Append a declaration for an open task to the ledger of ``cwd``'s
    repository. Refuses (DeclareRefused) on an unknown or closed task, an
    undeclarable stage, or an unchecked reference; the ledger is then unchanged."""
    path = ledger_path(cwd)
    if stage not in DECLARABLE:
        raise DeclareRefused(f"stage {stage} is proven by the transcript, not declared; "
                             f"declarable: {', '.join(DECLARABLE)}")
    if not any(r.get("open") == task_id for r in open_tasks(read_rows(path))):
        raise DeclareRefused(f"no open task {task_id} in {path}")
    kind, value = _kind_and_ref(cwd, stage, ref)
    row = {"declare": task_id, "stage": stage, "kind": kind, "ref": value, "time": now_iso()}
    append_row(path, row)
    return row


def close(path: str, task_id: str, verdict: Dict, scanned: tuple) -> Dict:
    """Append the close row. Pre: ``verdict`` holds "evidence", "missing" and
    "counts"; ``scanned`` is (window_end, transcript_path), how far which
    transcript was read. A verdict with missing stages closes only through the
    emergency switch, so its row is marked as a bypass."""
    window_end, transcript_path = scanned
    row = {"close": task_id, "evidence": verdict["evidence"], "counts": verdict["counts"],
           "window_end": window_end, "transcript_path": transcript_path, "time": now_iso()}
    if verdict.get("missing"):
        row.update(bypass=True, missing=verdict["missing"])
    append_row(path, row)
    return row


def metrics(rows: List[Dict]) -> Dict[str, Dict]:
    """agent_type -> {"tasks", "declared", "proven", "promise_rate", "reopens", "bypasses"}."""
    types = {r["open"]: r.get("agent_type") or MAIN_AGENT for r in rows if isinstance(r.get("open"), str)}
    out: Dict[str, Dict] = {}
    for r in (r for r in rows if isinstance(r.get("close"), str)):
        m = out.setdefault(types.get(r["close"], "?"), {"tasks": 0, "declared": 0, "proven": 0,
                                                       "reopens": 0, "bypasses": 0})
        if r.get("bypass"):
            m["bypasses"] += 1
            continue
        sources = [e.get("source") for e in (r.get("evidence") or {}).values()]
        m["tasks"] += 1
        m["declared"] += sources.count("declaration")
        m["proven"] += sources.count("transcript")
        m["reopens"] += (r.get("counts") or {}).get("reopens", 0)
    for m in out.values():
        total = m["declared"] + m["proven"]
        m["promise_rate"] = round(m["declared"] / total, 4) if total else None
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cycle_ledger.py",
                                     description="List, declare and measure per-task engineering cycles.")
    parser.add_argument("--cwd", default=os.getcwd(), help="directory inside the repository whose ledger to use")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print the open tasks")
    sub.add_parser("metrics", help="print the pre-registered metric per agent type, as JSON")
    dec = sub.add_parser("declare", help="declare a stage of an open task with a checkable reference")
    dec.add_argument("task_id")
    dec.add_argument("--stage", required=True, choices=sorted(DECLARABLE))
    dec.add_argument("--command", dest="ref_command", help="stage check: the command that proves the task")
    dec.add_argument("--sha", help="a commit of this repository")
    dec.add_argument("--url", help="a GitHub pull-request or issue URL")
    dec.add_argument("--memory-id", type=int, help="the id Cortex `remember` returned")
    dec.add_argument("--not-applicable", dest="na", help="stage benchmark: why nothing is measurable")
    return parser


def _listing(task: Dict) -> str:
    return f"{task['open']}\t{task.get('agent_type')}\t{task.get('session_id')}\t{task.get('first_path')}"


def _run(args) -> str:
    path = ledger_path(args.cwd)
    rows = read_rows(path)
    if args.command == "list":
        return "\n".join(_listing(r) for r in open_tasks(rows))
    if args.command == "metrics":
        return json.dumps(metrics(rows), indent=2, sort_keys=True)
    ref = {"command": args.ref_command, "sha": args.sha, "url": args.url,
           "memory": args.memory_id, "n/a": args.na}
    row = declare(args.cwd, args.task_id, args.stage, ref)
    return f"declared {row['stage']} of {row['declare']}: {row['kind']} {row['ref']}"


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        text = _run(args)
    except (LedgerError, DeclareRefused) as exc:
        print(f"[cycle-ledger] {exc}", file=sys.stderr)
        return 2
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
