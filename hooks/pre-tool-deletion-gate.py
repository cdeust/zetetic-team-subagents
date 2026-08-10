#!/usr/bin/env python3
"""pre-tool-deletion-gate.py — PreToolUse hook: block an Edit/Write that
removes a top-level definition while a live reference to it survives.

This is Tier 1 of the deletion gate (tools/deletion_gate.py owns the
mechanism and the message text; this hook is a caller of it, not a
reimplementation — coding-standards.md S1.2 Open/Closed). It runs BEFORE the
edit lands, so it stops the pattern at the moment of the act rather than
reporting it after a commit and a push: an Edit/Write hook sees
old_string/new_string (or content) directly, which a post-hoc CI diff never
gets to intervene on.

Three tiers total, and each catches what the others cannot:
  Tier 1 (here)                — blocks at the moment of the Edit/Write.
  Tier 2 (post-tool-deletion-gate.py, PostToolUse on Edit|Write|Bash) — the
                                  net: reads the actual working tree after
                                  ANY tool call, so a removal that arrived
                                  via `sed`/`rm`/`git rm`/a patch/a multi-step
                                  edit — none of which this hook's
                                  old_string/new_string payload can see — is
                                  still caught.
  Tier 3 (tools/deletion-gate.sh, the .githooks/pre-commit native git hook,
          and the `deletion-gate` CI job) — the commit/CI-range check, the
          only place a Retired-Because: trailer can be verified (no commit
          exists yet at Tier 1 or 2).

FAIL-CLOSED ON "CANNOT DETERMINE", not fail-open. A removed definition whose
survivor search errors out (PCRE-less git, a git failure, a repo state this
gate cannot read) BLOCKS with a message naming the problem and how to fix
it — it does not silently pass. Earlier revisions of this hook failed open
on GitError on the theory that Tier 3 always catches what Tier 1 misses;
checked against this repo's actual GitHub settings
(`gh api repos/.../branches/main/protection` -> 404 "Branch not protected",
verified 2026-08-10) that theory does not hold — main has no required status
checks, so a direct push or a web-UI merge bypasses CI entirely, and
`.githooks/pre-commit` is opt-in per clone (`tools/install-git-hooks.sh`),
not automatic. With no dependable backstop, "cannot verify" and "safe to
proceed" are not the same claim, and this hook must not conflate them.
Tier 1's remaining fail-OPEN paths (an unparseable stdin event, a file
outside the scope this gate covers) are genuinely "nothing to check" rather
than "checked and inconclusive" — see _read_event/_target_edit.

Reads the Claude Code tool-event JSON from stdin:
    {"tool_name": "Edit"|"Write", "tool_input": {...}}
Exits 2 (blocking, with an actionable message on stderr) when a removed
definition either has a live caller or could not be verified; exits 0 when
there is genuinely nothing this hook covers to check.
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
import deletion_gate_lang as dgl  # noqa: E402


def _resolve_repo_root(file_path: str) -> str:
    start = Path(file_path).resolve().parent
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else str(start)


def _repo_relative(repo: str, file_path: str) -> str:
    """git grep reports paths relative to the repo root; the exclude-path
    comparison in find_survivors needs the same form or it silently never
    matches (an absolute file_path would leave the file's own pre-image
    body — the thing about to be deleted — counted as a survivor)."""
    try:
        return str(Path(file_path).resolve().relative_to(Path(repo).resolve()))
    except ValueError:
        return file_path


def _post_image(tool: str, tin: dict, pre_text: str | None) -> str | None:
    if tool == "Write":
        content = tin.get("content")
        return content if isinstance(content, str) else None
    if tool == "Edit":
        old, new = tin.get("old_string"), tin.get("new_string")
        if pre_text is None or not isinstance(old, str) or not isinstance(new, str):
            return None
        if old not in pre_text:
            return None  # the edit itself will fail; not this hook's concern
        count = -1 if tin.get("replace_all") else 1
        return pre_text.replace(old, new, count)
    return None


def _removed_definitions(pre_text: str | None, post_text: str, lang: str) -> dict:
    pre_defs = dgl.extract_definitions(pre_text, lang) if pre_text else {}
    post_defs = dgl.extract_definitions(post_text, lang)
    return {name: kb for name, kb in pre_defs.items() if name not in post_defs}


def _block_reason(repo: str, rel_path: str, lang: str, removed: dict) -> str | None:
    """The first removed name with a live caller, formatted as a full
    actionable BLOCK message (module: dg.format_survivor_block) — the exact
    same words the CLI/CI Tier and Tier 2 show for the same defect."""
    for name, (kind, _body) in removed.items():
        survivors = dgg.find_survivors(
            repo, ref=None, mode=None, name=name, lang=lang, exclude_paths={rel_path}
        )
        if survivors:
            label = f"{rel_path}::{name} ({kind})"
            return dg.format_survivor_block(label, name, survivors)
    return None


def _indeterminate_reason(rel_path: str, removed: dict, exc: dgg.GitError) -> str:
    names = ", ".join(sorted(removed))
    return (
        f"BLOCK {rel_path} removes {names}, but whether any caller survives "
        f"could not be checked: {exc}\n"
        f"  Fix the problem named above (commonly: install a PCRE-enabled "
        f"git, or run this inside a real git checkout), then retry the "
        f"edit — this gate refuses to guess when it cannot verify."
    )


def _read_event() -> dict | None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    return event if isinstance(event, dict) else None


def _target_edit(event: dict) -> tuple:
    """(file_path, lang, tool, tin) for an Edit/Write worth gating, or all-None."""
    tool = event.get("tool_name", "")
    tin = event.get("tool_input") or {}
    if tool not in ("Edit", "Write") or not isinstance(tin, dict):
        return None, None, None, None
    file_path = tin.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return None, None, None, None
    lang = dgl.detect_lang(file_path)
    if lang is None or dgg.is_test_path(file_path):
        return None, None, None, None
    return file_path, lang, tool, tin


def _emit_block(reason: str) -> int:
    print(f"[deletion-gate] {reason}", file=sys.stderr)
    return 2


def main() -> int:
    event = _read_event()
    if event is None:
        return 0

    file_path, lang, tool, tin = _target_edit(event)
    if file_path is None:
        return 0

    path = Path(file_path)
    try:
        pre_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    except OSError:
        return 0

    post_text = _post_image(tool, tin, pre_text)
    if post_text is None or pre_text is None:
        return 0  # a brand-new file cannot have removed anything

    removed = _removed_definitions(pre_text, post_text, lang)
    if not removed:
        return 0

    repo = _resolve_repo_root(file_path)
    rel_path = _repo_relative(repo, file_path)
    try:
        reason = _block_reason(repo, rel_path, lang, removed)
    except dgg.GitError as exc:
        return _emit_block(_indeterminate_reason(rel_path, removed, exc))

    return _emit_block(reason) if reason is not None else 0


if __name__ == "__main__":
    sys.exit(main())
