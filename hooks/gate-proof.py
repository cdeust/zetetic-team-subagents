#!/usr/bin/env python3
"""PreToolUse gate (Bash): no `git commit` / `git push` / `gh pr create` of a tree that is not verified.

Rule (owner, 2026-09-30): only VALID, WORKING code is committed. Prose does not enforce that; this hook does.
Repatriated from ~/.claude/hooks/gate-proof.py (issue: no-timeouts programme PR-1); what changed:
the proof is the state of the async task `gate-<tree>` (tools/lib/tasks.py), not a file written by a
synchronous `scripts/gate.sh`, and there is no git timer (hooks/lib/gate_git.py).

  commit  tree = `git write-tree` (the index NOW);  push / gh pr create  tree = HEAD^{tree}.
  The task for that tree is started if absent (dedup by tree), then READ:
      done and green  -> allow          failed -> deny, naming the output file
      running         -> deny: "verification running for tree X; retry ... (status: ...)"
  This hook never waits and never decides on elapsed time. A green record for the tree is the cached
  proof, so a push of a committed tree reuses the commit's verification.

Which repos are gated and which checks run: hooks/lib/gate_config.py, docs/gate.md. Closed by default:
an unreadable payload, an unreadable repository or an invalid gate config in a gated repo exits 2.

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
import gate_git as gitq  # noqa: E402
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


def _declared(top: str) -> bool:
    try:
        return config.declaration(top) is not None
    except config.ConfigError as exc:
        raise _Deny(f"GATE-PROOF: the gate config of {top} is invalid ({exc}): refused (closed).") from exc


def _check(act: dict) -> None:
    """Raise _Deny if ``act`` must be refused; return None if allowed or not applicable."""
    if not os.path.isdir(act["dir"]):
        return  # the command itself will fail; nothing to judge
    repo = _locate(act["dir"])
    if repo is None or not _declared(repo.top):
        return
    try:
        if act["kind"] == "commit":
            if act["why"]:
                raise _Deny(_STAGE_SEPARATELY.format(why="; ".join(act["why"]), top=repo.top))
            trees = state.commit_trees(repo.top, act["amend"], act["allow_empty"])
        else:
            trees = state.push_trees(repo.top)
        if trees is None:
            return
        verdict = state.check(repo.top, act["kind"], trees[0], trees[1])
    except gitq.Unavailable as exc:
        raise _Deny(f"GATE-PROOF: cannot judge the tree ({exc}) in {repo.top}: refused (closed).") from exc
    if not verdict.allow:
        raise _Deny(verdict.message)


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
    try:
        return config.declared_above(directory)
    except Exception:  # FAILS_ON: the declaration probe itself failed; then nothing is known to be declared
        return False


def main() -> int:
    raw = sys.stdin.read()
    cwd_guess = os.getcwd()
    try:
        try:
            event = json.loads(raw)
        except ValueError:
            if config.declared_above(cwd_guess):
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
