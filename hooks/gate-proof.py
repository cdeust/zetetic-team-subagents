#!/usr/bin/env python3
"""PreToolUse gate (Bash): no `git commit` / `git push` / `gh pr create` of a tree that is not verified.

Rule (owner, 2026-09-30): only VALID, WORKING code is committed. Prose does not enforce that; this hook does.
Repatriated from ~/.claude/hooks/gate-proof.py (issue: no-timeouts programme PR-1); what changed:
the proof is the state of an async task (tools/lib/tasks.py) keyed by verb + tree + rules digest
(hooks/lib/gate_state.py), not a file written by a synchronous `scripts/gate.sh`, and there is no git timer.

  commit  tree = `git write-tree` (the index NOW).   The task for it is started if absent (dedup by key),
  push    the tip tree of EVERY ref the command      then READ:
          publishes (hooks/lib/gate_publish.py):         done and green -> allow   failed -> deny, naming
          `push origin feat`, `feat:main`, `--all`,      the output file   running -> deny: "verification
          `gh pr create --head feat`, the current        running for tree X; retry ..." A push needs a
          branch when none is named. A ref that does     push-kind green record: a commit's never stands in.
          not resolve to a commit is denied with the reason.
  This hook never waits and never decides on elapsed time.

Which repos are gated and which checks run: the rules of a TRUSTED tree (HEAD's; hooks/lib/gate_rules.py),
never the working copy and never the staged change alone, so a change cannot approve itself. A repository that
declares a gate but is not in ~/.claude/zetetic/gate-trusted-repos is denied, with the line to add, and nothing
runs (hooks/lib/gate_trust.py). Closed by default: an unreadable payload, an unreadable repository or an
invalid gate config in a gated repo exits 2. Registered with onFailure "block" (hooks/hooks.json), so a hook
that cannot finish refuses the call instead of letting it through (docs/gate.md, "A hook that is killed").

Rule floor: rules may only grow without the owner, against HEAD's rules, the floor the user keeps for the
repository outside it (hooks/lib/gate_floor.py) and, for a push, the rules of each destination ref. When every
verdict of a call allows it, the rules it leaves in force are recorded in that floor (`raise`, or `set` when the
owner acknowledged a lower state); when a call is denied, HEAD's rules, which are in force, are recorded.

Commit: a call that stages in the same breath (`git add ... && git commit`) or commits with
-a/--all/-i/-o/-p/explicit paths makes the index at hook time differ from the index that will be
committed, so the tree cannot be judged -> denied.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import gate_actions as actions  # noqa: E402
import gate_config as config  # noqa: E402
import gate_floor as floor  # noqa: E402
import gate_git as gitq  # noqa: E402
import gate_publish as publish  # noqa: E402
import gate_state as state  # noqa: E402

_STAGE_SEPARATELY = (
    "GATE-PROOF: stage in a separate call, then commit alone, without -a. The command {why}: the index "
    "at hook time is not the index of the commit, so the tree being committed cannot be judged.\n"
    "Run `git add <files>` in one call, then `git commit -m ...` alone (no -a/--all/-i/-o/paths).\n"
    "Repository: {top}"
)


class _Deny(Exception):
    pass


def _locate(directory: str) -> gitq.Repo | None:
    """The repository of ``directory``; None when it is not gated (not a repo, or no declaration above it)."""
    try:
        repo = gitq.locate(directory)
    except gitq.Unavailable as exc:
        if config.declared_above(directory):
            raise _Deny(f"GATE-PROOF: git unavailable ({exc}) in a repository that declares a gate: refused (closed).")
        return None
    if repo is None and config.declared_above(directory):
        raise _Deny("GATE-PROOF: repository unreadable although a gate is declared above this directory: refused (closed).")
    return repo


def _verdicts(repo: gitq.Repo, act: dict) -> list:
    """[(label, Verdict)] for what ``act`` would commit or publish; [] when there is nothing to judge."""
    if act["kind"] == "commit":
        if act["why"]:
            raise _Deny(_STAGE_SEPARATELY.format(why="; ".join(act["why"]), top=repo.top))
        trees = state.commit_trees(repo.top, act["amend"], act["allow_empty"])
        return [] if trees is None else [("", state.check(repo.top, "commit", trees[0], trees[1]))]
    try:
        tips = publish.resolve(repo.top, act["publish"])
    except publish.Unresolvable as exc:
        raise _Deny(f"GATE-PROOF: cannot tell which commits this publishes ({exc}): refused (closed).") from exc
    return [(f"[{tip.name}] ", state.judge(repo.top, "push", state.Change(tip.tree, tip.base, tip.dests))) for tip in tips]


def _settle(repo: gitq.Repo, kind: str, verdicts: list) -> str:
    """Record in the floor what the call leaves in force (all allowed) or what it observed (denied); "" when done.
    Allowed and not recordable: raise _Deny (the floor would not hold what was let through). Denied: the reason
    the observation could not be recorded, to append to the denial."""
    concerned = [v for v in verdicts if v.ends]
    heads = [v.head for v in concerned if v.head is not None]
    allowed = all(v.allow for v in verdicts)
    in_force = [s for v in concerned for s in v.ends] + (heads if kind == "push" else []) if allowed else heads
    if not in_force:
        return ""
    try:
        floor.record(repo.top, repo.common, in_force, allowed and any(v.acked for v in concerned))
    except (floor.Unreadable, OSError) as exc:  # FAILS_ON: the floor file cannot be read or written
        if allowed:
            raise _Deny(f"GATE-PROOF: the rule floor of {repo.top} cannot be recorded ({exc}): refused (closed). "
                        "See docs/gate.md (rule changes).") from exc
        return f"\n(The rules in force could not be recorded in the floor: {exc}.)"
    return ""


def _check(act: dict) -> None:
    """Raise _Deny if ``act`` must be refused; return None if allowed or not applicable."""
    if not os.path.isdir(act["dir"]):
        return  # the command itself will fail; nothing to judge
    repo = _locate(act["dir"])
    if repo is None:
        return
    try:
        verdicts = _verdicts(repo, act)
        denied = [label + v.message for label, v in verdicts if not v.allow]
        note = _settle(repo, act["kind"], [v for _, v in verdicts])
    except gitq.Unavailable as exc:
        raise _Deny(f"GATE-PROOF: cannot judge the tree ({exc}) in {repo.top}: refused (closed).") from exc
    if denied:
        raise _Deny(chr(10).join(denied) + note)


def _run(event: object) -> None:
    if not isinstance(event, dict):
        raise ValueError("payload is not an object")
    if event.get("tool_name") not in (None, "Bash"):
        return
    command = (event.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or ("git" not in command and "gh" not in command):
        return
    base = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    for act in actions.actions(command, base):
        if act["kind"] in ("commit", "push"):
            _check(act)


def _declared_above_safely(directory: str) -> bool:
    """True when a gate is declared above ``directory`` or the user keeps a rule floor for its repository: then a
    crash of this hook refuses the call (an orphan branch declares nothing, its floor still holds)."""
    try:
        return config.declared_above(directory) or floor.kept_for(directory)
    except Exception:  # FAILS_ON: the declaration probe itself failed; then nothing is known to be declared
        return False


def main() -> int:
    raw = sys.stdin.read()
    cwd_guess = os.getcwd()
    try:
        try:
            event = json.loads(raw)
        except ValueError:
            if _declared_above_safely(cwd_guess):
                print("GATE-PROOF: hook payload unreadable (invalid JSON) in a repository that declares a gate: "
                      "refused (closed). A gate that opens when it cannot read what it judges is not a gate.",
                      file=sys.stderr)
                return 2
            return 0
        if isinstance(event, dict) and isinstance(event.get("cwd"), str):
            cwd_guess = event["cwd"]
        _run(event)
        return 0
    except _Deny as deny:
        print(deny, file=sys.stderr)
        return 2
    except Exception as exc:  # FAILS_ON: any bug in this hook; blocks only where a gate is declared.
        if _declared_above_safely(cwd_guess):
            print(f"GATE-PROOF: the hook crashed ({exc.__class__.__name__}: {exc}) in a repository that "
                  "declares a gate: refused (closed). Fix hooks/gate-proof.py.", file=sys.stderr)
            return 2
        return 0


if __name__ == "__main__":
    sys.exit(main())
