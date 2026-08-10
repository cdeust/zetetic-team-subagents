#!/usr/bin/env python3
"""pre-tool-deletion-gate.py — PreToolUse hook: block an Edit/Write that
removes a top-level definition while a live reference to it survives.

This is Tier 1 of the deletion gate (tools/deletion_gate.py owns the
mechanism; this hook is a caller of it, not a reimplementation —
coding-standards.md S1.2 Open/Closed). It runs BEFORE the edit lands, so it
stops the pattern at the moment of the act rather than reporting it after a
commit and a push: an Edit/Write hook sees old_string/new_string (or
content) directly, which a post-hoc CI diff never gets to intervene on.

What it does NOT do: require a Retired-Because: trailer. There is no commit
yet at edit time, so "no survivors, no trailer" cannot be evaluated here —
that half of the contract is Tier 2, tools/deletion_gate.py run at commit/CI
time (tools/deletion-gate.sh, wired in .github/workflows/ci.yml and
memory/acceptance-gates.yaml). This hook only ever fires the survivors-found
BLOCK, which is unconditional and needs no message.

Reads the Claude Code tool-event JSON from stdin:
    {"tool_name": "Edit"|"Write", "tool_input": {...}}
Exits 2 (blocking) with the surviving callers on stderr when a removed
definition still has one; exits 0 otherwise, including on every input this
hook cannot confidently parse (fail-open for the TOOL CALL — the commit-time
gate is what fails closed on ambiguity; a PreToolUse hook that block-by-
default on parse noise would freeze ordinary editing, coding-standards.md
S10 stakes calibration: this is the low-cost early check, not the gate).
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
    pre_defs = dg.extract_definitions(pre_text, lang) if pre_text else {}
    post_defs = dg.extract_definitions(post_text, lang)
    return {name: kb for name, kb in pre_defs.items() if name not in post_defs}


def _block_reason(repo: str, rel_path: str, lang: str, removed: dict) -> str | None:
    for name, (kind, _body) in removed.items():
        survivors = dg.find_survivors(
            repo, ref=None, staged=False, name=name, lang=lang, exclude_path=rel_path
        )
        if survivors:
            detail = "; ".join(survivors[:8])
            return (
                f"deletion-gate: removing {rel_path}::{name} ({kind}) would leave "
                f"{len(survivors)} surviving reference(s): {detail}"
            )
    return None


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
    lang = dg.detect_lang(file_path)
    if lang is None or dg.is_test_path(file_path):
        return None, None, None, None
    return file_path, lang, tool, tin


def _emit_block(reason: str) -> int:
    print(f"[deletion-gate] {reason}", file=sys.stderr)
    print(
        "[deletion-gate] Fix the caller(s), or rename/move the definition "
        "(the body must reappear elsewhere for that to be recognized), or "
        "commit with a Retired-Because: trailer explaining why the job no "
        "longer needs doing (enforced at commit/CI time by "
        "tools/deletion-gate.sh).",
        file=sys.stderr,
    )
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

    try:
        repo = _resolve_repo_root(file_path)
        rel_path = _repo_relative(repo, file_path)
        reason = _block_reason(repo, rel_path, lang, removed)
    except dg.GitError:
        return 0  # can't determine -> the commit-time gate fails closed instead

    return _emit_block(reason) if reason is not None else 0


if __name__ == "__main__":
    sys.exit(main())
