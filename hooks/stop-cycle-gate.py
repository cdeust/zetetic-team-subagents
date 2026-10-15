#!/usr/bin/env python3
"""stop-cycle-gate.py -- Stop and SubagentStop hook: no stop on an unproven task.

Closes the cycle tasks opened by ``post-edit-cycle-open.py`` (ledger:
``tools/cycle_ledger.py``; evidence rules: ``tools/cycle_evidence.py``). On each
stop it reads the stopping agent's transcript from the task's window start;
when every stage of ``commands/zetetic/engineering-loop.md`` is proven it
appends the close row and lets the agent stop, otherwise it BLOCKS with the
stages still missing and the exact way to prove each.

BLOCK BY DEFAULT. Owner decision 1 of 2026-10-13 (Cortex memory
cycle-ledger-pr2-decisions) deliberately overrides this repository's lesson of
2026-06-10 that broad Stop checks warn by default and block on opt-in
(``stop-zetetic-spine.py``, ``stop-acceptance-gate.py``). Do not "fix" this
back to a warning. The emergency switch is ``ZETETIC_CYCLE_GATE=off`` in the
environment Claude Code was started with; an unproven task it lets through is
CLOSED with a bypass close row naming the stages it skipped, so each task is
logged once and the next stop starts a fresh task.

Which tasks. ``Stop`` fires for the main agent (hooks reference: "Runs when the
main Claude Code agent has finished responding"): its tasks have a null
agent_id. ``SubagentStop`` carries agent_id and ``agent_transcript_path``, "the
subagent's own transcript"; the run is identified by
``reflection_subagent.resolve_run``. Attribution follows stop-reflection-gate:
tasks recorded without a session_id block the main agent and are named
unattributed, and each is judged on the transcript recorded when it opened,
never on this session's; a Stop payload without a session_id cannot tell its
tasks apart, so every open main-agent task blocks, and the reason says why.
Tasks of other sessions or agents never block this one; their count goes to stderr.

Loop rule, as in the other Stop gates: a forced continuation
(``stop_hook_active``) is never blocked again; what is still missing goes to
stderr. A transcript that cannot be read proves nothing: the task blocks.

Pre: stdin is the Stop or SubagentStop event JSON. Post: stdout holds a block
decision iff a task of the stopping agent is unproven, stop_hook_active is
false and the switch is not off; a proven task gains exactly one close row.
"""
from __future__ import annotations

import json
import os
import sys

_TOOL = "cycle-gate"
_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
_LEDGER_TOOL = os.path.join(_ROOT, "tools", "cycle_ledger.py")
SWITCH = "ZETETIC_CYCLE_GATE"


def say(message: str) -> None:
    print(f"[{_TOOL}] {message}", file=sys.stderr)


def _stopping_agent(payload: dict, reflection_subagent, gates_jsonl) -> tuple:
    """(session_id or None, agent_id or None, transcript path, caveats)."""
    session = gates_jsonl.text(payload.get("session_id")) or None
    if payload.get("hook_event_name") != "SubagentStop":
        return session, None, gates_jsonl.text(payload.get("transcript_path")), []
    run = reflection_subagent.resolve_run(payload)
    return session, run.agent_id, run.transcript_path, list(run.notes)


def _mine(cycle_ledger, rows: list, stopping: tuple) -> tuple:
    """([(task, transcript to judge it on)] that block this stop, caveats).

    A main-agent task that is not this session's is judged on its own recorded
    transcript: this session's transcript cannot prove another session's work.
    A subagent's tasks are judged on the stopping subagent's transcript, the
    only file that holds its work (its tool events carry the parent's path);
    agent ids are unique, so a null-session task of this agent_id is its own."""
    session, agent_id, transcript = stopping
    every = cycle_ledger.open_tasks(rows)
    if session is None:
        mine = [t for t in every if t.get("agent_id") == agent_id]
        return [(t, transcript if agent_id else t.get("transcript_path") or "") for t in mine], [
            f"the payload carries no session_id: all {len(mine)} open task(s) of this agent block"] if mine else []
    mine = cycle_ledger.open_tasks(rows, (session, agent_id))
    if agent_id:
        mine += cycle_ledger.open_tasks(rows, (None, agent_id))
    orphans = [t for t in every if t.get("session_id") is None and agent_id is None and t.get("agent_id") is None]
    caveats = [f"{len(orphans)} task(s) were recorded without a session_id and are unattributed; they block "
               "until proven on their own transcript"] if orphans else []
    return [(t, transcript) for t in mine] + [(t, t.get("transcript_path") or "") for t in orphans], caveats


def _task_file_test(cycle_evidence, cycle_ledger, calls: list):
    """"Is this an edit of a task file" for cycle_evidence.evaluate, answered
    for every edited path of ``calls`` with one batch of git calls. When git
    cannot answer, every edit counts (fail closed) and stderr says so."""
    try:
        repos = cycle_ledger.task_repos(cycle_evidence.edited_paths(calls))
    except cycle_ledger.LedgerError as exc:
        say(f"git could not classify the edited paths, every edit counts as a task edit: {exc}")
        return bool
    return lambda path: repos.get(path) is not None


def _verdict(tools, task: dict, decls: dict, transcript: str) -> tuple:
    """(verdict, end offset). An unreadable transcript proves nothing."""
    cycle_evidence, cycle_ledger = tools
    try:
        calls, end = cycle_evidence.scan(transcript, int(task.get("window_start") or 0))
    except (OSError, TypeError, ValueError) as exc:
        return {"evidence": {}, "missing": list(cycle_evidence.STAGES), "counts": {},
                "error": f"transcript {transcript!r} unreadable: {exc}"}, 0
    return cycle_evidence.evaluate(calls, decls, _task_file_test(cycle_evidence, cycle_ledger, calls)), end


def _task_text(cycle_evidence, task: dict, verdict: dict, cwd: str) -> str:
    tool = f"python3 {_LEDGER_TOOL} --cwd {cwd}"
    lines = [f"- task {task['open']} ({task.get('agent_type')}; opened at {task.get('first_path')})"]
    if verdict.get("error"):
        lines.append(f"  {verdict['error']}")
    if task.get("repo") and not os.path.isdir(task["repo"]):
        lines.append(f"  its worktree {task['repo']} is gone; if its work was pushed: {tool} close-disposed "
                     f"{task['open']} --url <pull request> --sha <pushed commit>")
    lines +=[f"  {stage}: " + cycle_evidence.HOW[stage].format(tool=tool, task=task["open"])
              for stage in verdict["missing"]]
    return "\n".join(lines)


def block_reason(cycle_evidence, unproven: list, cwd: str, caveats: list) -> str:
    return "".join(f"NOTE: {c}\n" for c in caveats) + (
        f"{len(unproven)} engineering cycle task(s) not proven. A task that changed code closes only "
        "when every stage of /zetetic:engineering-loop is proven (check, recall, refine, investigate, "
        "implement, verify, benchmark, review, remember). Prove the missing stages below, then stop "
        "again; the gate re-reads the transcript.\n"
        + "\n".join(_task_text(cycle_evidence, u["task"], u["verdict"], cwd) for u in unproven))


def _settle(tools, path: str, rows: list, judged: list) -> list:
    """Close every proven task; return the unproven ones as
    {"task", "verdict", "end", "transcript"}."""
    cycle_evidence, cycle_ledger = tools
    unproven = []
    for task, transcript in judged:
        verdict, end = _verdict(tools, task, cycle_ledger.declarations(rows, task["open"]), transcript)
        if verdict["missing"]:
            unproven.append({"task": task, "verdict": verdict, "end": end, "transcript": transcript})
        else:
            cycle_ledger.close(path, task["open"], verdict, (end, transcript))
            say(f"cycle task {task['open']} closed: every stage proven")
    return unproven


def _let_through(tools, path: str, unproven: list, payload: dict) -> bool:
    """True when the stop goes through despite unproven tasks (switch off, or a
    forced continuation), after closing them as bypassed or reporting why."""
    _, cycle_ledger = tools
    if os.environ.get(SWITCH, "").lower() == "off":
        for u in unproven:
            cycle_ledger.close(path, u["task"]["open"], u["verdict"], (u["end"], u["transcript"]))
        say(f"{SWITCH}=off: {len(unproven)} unproven task(s) let through and closed as bypassed in {path}")
        return True
    if payload.get("stop_hook_active"):
        say(f"{len(unproven)} task(s) still unproven, stop allowed because this is a forced continuation: "
            + ", ".join(f"{u['task']['open']} missing {'/'.join(u['verdict']['missing'])}" for u in unproven))
        return True
    return False


def _load():
    import cycle_evidence
    import cycle_ledger
    import gates_jsonl
    import reflection_subagent
    return cycle_evidence, cycle_ledger, gates_jsonl, reflection_subagent


def main() -> int:
    try:
        cycle_evidence, cycle_ledger, gates_jsonl, reflection_subagent = _load()
    except ImportError as exc:  # FAILS_ON: tools/ not shipped beside hooks/ (partial install)
        say(f"cannot load tools/cycle_*.py, cycles not enforced: {exc}")
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        say(f"stdin is not JSON, cycles not enforced: {exc}")
        return 0
    if not isinstance(payload, dict):
        say("stdin is not a JSON object, cycles not enforced")
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    tools = (cycle_evidence, cycle_ledger)
    try:
        path = cycle_ledger.ledger_path(cwd)
    except cycle_ledger.LedgerError:
        return 0  # not a git repository: the opener said so when it recorded a task elsewhere
    try:
        session, agent_id, transcript, notes = _stopping_agent(payload, reflection_subagent, gates_jsonl)
        rows = cycle_ledger.read_rows(path)
        judged, caveats = _mine(cycle_ledger, rows, (session, agent_id, transcript))
        others = len(cycle_ledger.open_tasks(rows)) - len(judged)
        if others:
            say(f"{others} open task(s) belong to other sessions or agents: python3 {_LEDGER_TOOL} --cwd {cwd} list")
        unproven = _settle(tools, path, rows, judged)
    except reflection_subagent.RunUnidentified as exc:
        say(f"cannot identify the stopping subagent, its tasks are not enforced: {exc}")
        return 0
    except cycle_ledger.LedgerError as exc:
        say(f"ledger unusable, cycles NOT enforced: {exc}")
        return 0
    for caveat in caveats + notes:
        say(caveat)
    if unproven and not _let_through(tools, path, unproven, payload):
        sys.stdout.write(json.dumps({"decision": "block",
                                     "reason": block_reason(cycle_evidence, unproven, cwd, caveats)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
