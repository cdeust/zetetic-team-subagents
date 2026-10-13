#!/usr/bin/env python3
"""cycle_evidence.py -- what a transcript proves about the stages of one task.

``scan`` reads a Claude Code JSONL transcript forward from the task's window
start and returns its tool calls in order, each paired with its result's
``is_error``. ``evaluate`` turns those calls plus the task's declarations
(``cycle_ledger.declarations``) into a verdict: the evidence of every proven
stage, the stages still missing with how to prove them, and the counts the
metric needs.

Transcript facts relied on (checked on the owner's transcripts 2026-10-13,
``~/.claude/projects/<proj>/<session>.jsonl``): an assistant line carries
``message.content`` blocks of type ``tool_use`` {id, name, input}; the result
comes back on a later user line as a ``tool_result`` block {tool_use_id,
is_error}; a Bash command that exits non-zero has ``is_error: true`` (observed:
the first Bash of session 65edc922, "Exit code 1").

Stage rules (engineering-loop.md steps 0-8). "After the last edit" means a
later position in the window than the last edit of a task file:
  check       declared command (cycle_ledger), shown run by verify
  recall      a Cortex recall/unified_search/recall_hierarchical/navigate_memory call
  refine      a Skill call whose skill names "refine", or a declaration
  investigate a Read, Grep or Glob call, or a Bash command that reads (cat, head,
              tail, sed -n, grep, rg, find, ls, wc, git show/diff/log/grep/blame)
  implement   an Edit/Write/MultiEdit/NotebookEdit of a task file
  verify      a foreground Bash call whose command IS the declared check
              (optionally after one ``cd <dir> &&``), after the last edit,
              whose result is not an error. Equality, not containment: a pipe
              exits with its last command's status (``CHECK | tail``), and
              ``CHECK || true`` or ``echo CHECK`` exit 0 whatever CHECK does
  benchmark   a declaration (a reference, or not applicable with the reason)
  review      a Skill call of a review skill or an Agent call of a code
              reviewer (REVIEW_SKILLS, REVIEW_AGENT_SUFFIX), after the last edit
  remember    a Cortex remember call after the first edit

Complexity: one pass, O(bytes in the window); a line is JSON-decoded only when
it contains a tool_use or tool_result marker. The largest transcripts measured
on this machine are under 5 MB (ls -S ~/.claude/projects/*/*.jsonl, 2026-10-13).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional

# source: commands/zetetic/engineering-loop.md, "## Instructions", steps 0-8.
STAGES = ("check", "recall", "refine", "investigate", "implement", "verify",
          "benchmark", "review", "remember")
# source: hooks/stop-zetetic-spine.py CHANGE_RE (the edit tools it treats as a change).
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
INVESTIGATE_TOOLS = frozenset({"Read", "Grep", "Glob"})
# Reading through Bash counts too: Claude Code's auto mode tells the agent it may
# "read files with cat, head, or sed -n, search with grep and find", and the first
# live run of this gate (2026-10-13, session 65edc922) read every file that way.
# A segment of the command (split on | ; && ||) must START with the verb.
_BASH_READ = re.compile(r"(?:^|[|;&]\s*)(?:cd\s+\S+\s*&&\s*)?(?:cat|head|tail|sed\s+-n|grep|rg|find|ls"
                        r"|wc|git\s+(?:show|diff|log|grep|blame))\b")
# The subagent tool. source: every Agent tool_use in ~/.claude/projects/*/*.jsonl;
# no "Task" tool_use occurs in those transcripts (grep, 2026-10-13).
AGENT_TOOLS = frozenset({"Agent"})
# Any Cortex server prefix (plugin or user scope). source: tool names of this
# session, e.g. mcp__plugin_hypermnesia-mcp_cortex__recall.
_CORTEX_RECALL = re.compile(r"^mcp__.*cortex__(recall|unified_search|recall_hierarchical|navigate_memory)$")
_CORTEX_REMEMBER = re.compile(r"^mcp__.*cortex__remember$")
# Review skills, by exact name: a substring would also accept
# superpowers:receiving-code-review (taking review comments, not reviewing).
# source: the Skill listing of the owner's session 2026-10-13 ("code-review:
# Review the current diff ...", "zetetic:review: Quick Review"); no Skill call
# naming a review occurs in ~/.claude/projects/**/*.jsonl (scan, 2026-10-13).
REVIEW_SKILLS = frozenset({"code-review", "zetetic:review"})
# A code-reviewer agent of any plugin scope; reviewer-academic reviews papers.
# source: the only reviewer Agent call in ~/.claude/projects/**/*.jsonl
# (scan, 2026-10-13) has subagent_type "zetetic-team-subagents:code-reviewer".
REVIEW_AGENT_SUFFIX = "code-reviewer"
# The refine skill, by exact name: a substring would accept any skill whose
# name merely contains "refine". source: the Skill listing of the owner's
# session 2026-10-13 ("refine-gate:refine"; "/refine" when invoked unscoped).
REFINE_SKILLS = frozenset({"refine", "refine-gate:refine"})
# One leading "cd <dir> &&" before the declared check. source: the Bash calls
# of this session run from another cwd as "cd <worktree> && <command>".
_CD_PREFIX = re.compile(r"""^cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*&&\s*""")
_MARKERS = (b'"tool_use"', b'"tool_result"')
Calls = List[Dict]
Decls = Dict[str, Dict]
TaskFileTest = Callable[[str], bool]

HOW = {
    "check": "declare the command that proves this task: {tool} declare {task} --stage check --command \"<command>\"",
    "recall": "call Cortex recall on the area of this task (engineering-loop step 1)",
    "refine": "run /refine, or declare the refined spec: {tool} declare {task} --stage refine "
              "--url <issue/PR> | --sha <commit> | --memory-id <id>",
    "investigate": "read the code this task touches (Read, Grep, or cat/grep/sed -n in Bash) "
                   "before claiming anything about it",
    "implement": "no edit of a task file is in this transcript window",
    "verify": "run the declared check after the last edit, as the whole command (no pipe, no || true, "
              "not in the background); it must exit 0",
    "benchmark": "declare the measured delta: {tool} declare {task} --stage benchmark --sha <commit> | "
                 "--url <PR> | --memory-id <id>, or --not-applicable \"<why nothing is measurable>\"",
    "review": "review the diff after the last edit: the code-review or zetetic:review skill, "
              "or an Agent of type code-reviewer",
    "remember": "call Cortex remember with what a future session needs (engineering-loop step 8)",
}


def _uses_and_results(line: bytes, uses: List[Dict], results: Dict[str, bool]) -> None:
    try:
        row = json.loads(line.decode("utf-8", "replace"))
    except ValueError:
        return  # a torn line never hides the rest
    content = (row.get("message") or {}).get("content") if isinstance(row, dict) else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            uses.append({"id": block.get("id"), "name": block.get("name") or "",
                         "input": block.get("input") if isinstance(block.get("input"), dict) else {}})
        elif block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
            results[block["tool_use_id"]] = bool(block.get("is_error"))


def scan(transcript_path: str, start: int) -> tuple:
    """(calls, end offset). Each call: {"id", "name", "input", "is_error"} where
    is_error is None while no result is recorded. Raises OSError when the
    transcript cannot be read: the caller must not treat that as 'no evidence'."""
    uses: List[Dict] = []
    results: Dict[str, bool] = {}
    with open(transcript_path, "rb") as fh:
        fh.seek(start)
        for line in fh:
            if any(m in line for m in _MARKERS):
                _uses_and_results(line, uses, results)
        end = fh.tell()
    return [{**u, "is_error": results.get(u["id"])} for u in uses], end


def _investigation(call: Dict) -> bool:
    if call["name"] == "Bash":
        return bool(_BASH_READ.search(str(call["input"].get("command", ""))))
    return call["name"] in INVESTIGATE_TOOLS


def _review(call: Dict) -> bool:
    if call["name"] == "Skill":
        return str(call["input"].get("skill", "")) in REVIEW_SKILLS
    agent_type = str(call["input"].get("subagent_type", ""))
    return call["name"] in AGENT_TOOLS and (agent_type == REVIEW_AGENT_SUFFIX
                                            or agent_type.endswith(":" + REVIEW_AGENT_SUFFIX))


def _edited_path(call: Dict) -> str:
    return str(call["input"].get("file_path") or call["input"].get("notebook_path") or "")


def edited_paths(calls: Calls) -> List[str]:
    """The distinct non-empty paths the edit calls of ``calls`` touched."""
    return sorted({_edited_path(c) for c in calls if c["name"] in EDIT_TOOLS} - {""})


def _edits(calls: Calls, is_task_file: TaskFileTest) -> List[int]:
    return [i for i, c in enumerate(calls) if c["name"] in EDIT_TOOLS and is_task_file(_edited_path(c))]


def _first(calls: Calls, test: Callable[[Dict], bool], after: int = -1) -> Optional[str]:
    """Name of the first call after index ``after`` passing ``test``, else None."""
    return next((c["name"] for c in calls[after + 1:] if test(c)), None)


def runs_check(call: Dict, command: str) -> bool:
    """True when ``call`` is a foreground Bash run of exactly ``command``."""
    if call["name"] != "Bash" or call["input"].get("run_in_background"):
        return False
    ran = str(call["input"].get("command", "")).strip()
    return command.strip() in (ran, _CD_PREFIX.sub("", ran, count=1))


def _verified(calls: Calls, command: str, after: int) -> Optional[str]:
    for c in calls[after + 1:]:
        if runs_check(c, command) and c["is_error"] is False:
            return f"Bash ran `{command}` and it exited 0"
    return None


def _transcript_stages(calls: Calls, edits: List[int], decls: Decls) -> Dict[str, Optional[str]]:
    first, last = edits[0], edits[-1]
    check = decls.get("check", {}).get("ref")
    return {
        "recall": _first(calls, lambda c: bool(_CORTEX_RECALL.match(c["name"]))),
        "refine": _first(calls, lambda c: c["name"] == "Skill" and c["input"].get("skill") in REFINE_SKILLS),
        "investigate": _first(calls, _investigation),
        "implement": f"{len(edits)} edit(s) of task files",
        "verify": _verified(calls, check, last) if check else None,
        "review": _first(calls, _review, last),
        "remember": _first(calls, lambda c: bool(_CORTEX_REMEMBER.match(c["name"])), first),
    }


def _counts(calls: Calls, edits: List[int]) -> Dict[str, int]:
    reviews = [i for i, c in enumerate(calls) if _review(c) and i > edits[0]]
    return {"edits": len(edits), "reviews": len(reviews),
            "reopens": sum(1 for i in reviews if any(e > i for e in edits))}


def evaluate(calls: Calls, decls: Decls, is_task_file: TaskFileTest) -> Dict:
    """{"evidence": {stage: {"source", "detail"}}, "missing": [stage...], "counts": {...}}.

    Pre: ``calls`` come from ``scan`` over the task's window. A window without
    an edit of a task file proves no transcript stage (it cannot place 'after
    the last edit'), so everything but the declarations is missing."""
    edits = _edits(calls, is_task_file)
    found = _transcript_stages(calls, edits, decls) if edits else {}
    evidence: Dict[str, Dict] = {}
    for stage, detail in found.items():
        if detail:
            evidence[stage] = {"source": "transcript", "detail": detail}
    if "verify" in evidence:  # the declared command ran green: the check is proven by the run
        evidence["check"] = {"source": "transcript", "detail": decls["check"]["ref"]}
    for stage in ("refine", "benchmark"):
        if stage not in evidence and stage in decls:
            evidence[stage] = {"source": "declaration", "detail": f"{decls[stage]['kind']}: {decls[stage]['ref']}"}
    missing = [s for s in STAGES if s not in evidence]
    if "check" in missing and "check" in decls:
        missing.remove("check")  # declared; it closes when verify sees it run green
    counts = _counts(calls, edits) if edits else {"edits": 0, "reviews": 0, "reopens": 0}
    return {"evidence": evidence, "missing": missing, "counts": counts}
