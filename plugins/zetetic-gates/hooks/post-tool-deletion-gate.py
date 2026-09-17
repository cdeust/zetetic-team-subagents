#!/usr/bin/env python3
"""post-tool-deletion-gate.py — PostToolUse hook: the net for a removed
top-level definition that arrives by any path Tier 1 cannot see.

Tier 1 (pre-tool-deletion-gate.py, PreToolUse on Edit|Write) reasons about
one edit's old_string/new_string payload before it lands. That is
structurally blind to:
  - a removal made via Bash (`sed -i`, `rm`, `git rm`, applying a patch, a
    script that rewrites a file);
  - a `Write` of an entire new file, where there is no old_string at all —
    detecting a removal there needs the ON-DISK content, not the payload;
  - a removal that only exists as the SUM of several small edits, each
    individually unremarkable.

This hook runs AFTER the tool call, matched on Edit|Write|Bash, and reasons
about the REAL working tree instead: it diffs HEAD against the actual
on-disk state (tools/deletion_gate.py's --worktree mode) and asks the exact
same question Tier 1 and Tier 3 ask — did a removed top-level definition
leave a live caller. It cannot undo the tool call that already ran, but it
can refuse the turn to continue silently, by printing the actionable BLOCK
message (the words the agent needs to act on, per Anthropic's guidance that
a tool's error output IS its interface — see the shared formatters in
tools/deletion_gate.py) and exiting non-zero.

Cost: bounded by `git diff --name-status -M HEAD`, which is proportional to
the SIZE OF THE CHANGE since the last commit, not the size of the repo, so
this stays cheap on every Edit/Write/Bash regardless of tree size. The
survivor grep only runs when the diff actually shows a removed definition,
which is rare relative to the volume of ordinary edits.

No duplicate messaging with Tier 1: if Tier 1 blocked an Edit/Write, that
tool call never executed, so its change never reaches the working tree and
this hook never sees it. Anything this hook DOES catch is, by construction,
something Tier 1 did not (a different file, a Bash-originated change, or a
multi-step accumulation) — never a repeat of the same finding.

FAIL-CLOSED once a removal is found and verification cannot complete — same
discipline as Tier 1 (see that module's docstring for why "Tier 3 always
catches it" cannot be assumed: this repo's main has no branch protection,
verified 2026-08-10). FAIL-OPEN only for genuinely out-of-scope states: no
git repository at the working directory, or no HEAD commit yet to diff
against — there, there is no baseline to compare to at all, not "a removal
we could not verify".

Reads the Claude Code tool-event JSON from stdin:
    {"tool_name": "Edit"|"Write"|"Bash", "tool_input": {...}}
Exits 2 (blocking) with the actionable BLOCK message(s) on stderr when the
working tree shows a removed definition that fails the gate; exits 0
otherwise.
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path


def _resolve_tools_dir() -> Path:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    candidates = []
    if plugin_root:
        candidates.append(Path(plugin_root) / "tools")
    candidates.append(Path(__file__).resolve().parent.parent / "tools")
    for candidate in candidates:
        if (candidate / "deletion_gate.py").exists():
            return candidate
    return candidates[-1]


sys.path.insert(0, str(_resolve_tools_dir()))
import deletion_gate as dg  # noqa: E402  (path must be set first)
import deletion_gate_git as dgg  # noqa: E402

_WATCHED_TOOLS = ("Edit", "Write", "Bash")


def _resolve_repo_root(cwd: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _read_event() -> dict | None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    return event if isinstance(event, dict) else None


def _indeterminate_reason(removed: list, exc: "dgg.GitError") -> str:
    names = ", ".join(sorted({rd.name for rd in removed}))
    return (
        f"BLOCK the working tree removes {names}, but whether any caller "
        f"survives could not be checked: {exc}\n"
        f"  Fix the problem named above (commonly: install a PCRE-enabled "
        f"git, or run this inside a real git checkout), then retry — this "
        f"gate refuses to guess when it cannot verify."
    )


def _emit_block(messages: list) -> int:
    for message in messages:
        print(f"[deletion-gate/post] {message}", file=sys.stderr)
    return 2


def main() -> int:
    event = _read_event()
    if event is None:
        return 0
    if event.get("tool_name", "") not in _WATCHED_TOOLS:
        return 0

    repo = _resolve_repo_root(os.getcwd())
    if repo is None:
        return 0  # not inside a git repository -> nothing to diff against

    try:
        removed, _added = dgg.collect_definitions(repo, "HEAD", "HEAD", dgg.MODE_WORKTREE)
    except dgg.GitError:
        return 0  # no HEAD yet (fresh repo) -> no baseline, not "unverifiable"
    if not removed:
        return 0

    try:
        request = dg.GateRequest(
            repo, "HEAD", "HEAD", "", mode=dgg.MODE_WORKTREE, require_trailer=False
        )
        result = dg.evaluate(request)
    except dgg.GitError as exc:
        return _emit_block([_indeterminate_reason(removed, exc)])

    if not result.blocked:
        return 0
    return _emit_block([f.message for f in result.findings if f.blocked])


if __name__ == "__main__":
    sys.exit(main())
