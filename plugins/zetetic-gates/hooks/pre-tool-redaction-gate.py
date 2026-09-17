#!/usr/bin/env python3
"""pre-tool-redaction-gate.py — PreToolUse hook: the redaction gate on every
outbound action that carries prose.

The Stop gate holds every returned message to the inventory in
``skills/writing/redaction.md``. Messages are not the only prose that leaves a
session: a commit message, a pull-request body, an issue or a review comment
is published copy the moment the command runs, and none of it passes through
a Stop hook. This hook closes that path. It fires on ``Bash`` and on the
GitHub MCP tools (``mcp__github__*``), extracts the prose the action is about
to send, and runs it through ``tools/redaction-checker.sh --stdin``:

* ``git commit``: ``-m``/``--message`` values, ``-F``/``--file`` contents.
* ``gh pr|issue|release create|comment|review|edit``: ``--body``/``-b``,
  ``--title``/``-t``, ``--notes``/``-n`` values; ``--body-file``/``-F``/
  ``--notes-file`` contents (read relative to the event's ``cwd``).
* GitHub MCP tools: the ``body``, ``title``, ``commit_message``, ``text``,
  ``description`` and ``notes`` fields of ``tool_input``.

A command whose quoting the shell tokenizer cannot resolve (an unbalanced
quote inside a heredoc, say) is scanned as raw text: the prose is still in
it, and a few non-copy lines cost nothing. A command carrying none of the
verbs above exits immediately, because the ``Bash`` matcher fires on every
shell call and this must stay cheap.

Same two tiers and the same opt-in as the Stop gate (``tools/redaction_gate.py``
is the shared mechanism): WARN on stderr by default (exit 0, the action
proceeds); BLOCK when ``REDACTION_STOP_BLOCK=on`` or ``.redaction-gate.json``
exists at the repo root (exit 2, the action is refused and the reason is
handed back for the rewrite). ``REDACTION_STOP_WARN=off`` silences the
warning tier. Fail-open on a missing module or checker, a malformed payload
or an unreadable body file.
"""
import json
import os
import re
import shlex
import sys
from typing import Dict, List, Set

# A command position (line start or after a shell separator), optional git
# global flags (each with an optional non-dash argument, so `-C /tmp` passes),
# then the verb not followed by `-` or a word character (so `commit-tree` and
# `commit-graph` do not fire). Same anchoring as pre-commit-zetetic.sh's
# GIT_VERB_RE so `echo "git commit"` does not fire either.
PROSE_VERB_RE = re.compile(
    r"(?:^|[;&|({]\s*)(?:\S*/)?(?:(git)\s+(?:-\S+(?:\s+[^-\s]\S*)?\s+)*commit(?![-\w])"
    r"|(gh)\s+(?:pr|issue|release)\s+(?:create|comment|review|edit)(?![-\w]))")

# Which flags carry prose inline and which name a file, per verb. ``-n`` is
# ``--notes`` for gh but ``--no-verify`` for git commit (no argument), and
# ``-F`` is ``--file`` for git but ``--body-file`` for gh: the sets are keyed
# by verb so one never consumes the other's flag.
INLINE_FLAGS: Dict[str, Set[str]] = {
    "git": {"-m", "--message"},
    "gh": {"-b", "--body", "-t", "--title", "-n", "--notes"},
}
FILE_FLAGS: Dict[str, Set[str]] = {
    "git": {"-F", "--file"},
    "gh": {"-F", "--body-file", "--notes-file"},
}
MCP_PROSE_FIELDS = ("body", "title", "commit_message", "text", "description", "notes")
MCP_PREFIX = "mcp__github__"


def _load_gate():
    """Import tools/redaction_gate.py from beside this hook or the plugin root;
    None when no copy exists (fail open, like a missing checker)."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "tools")]
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "tools"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(os.path.join(c, "redaction_gate.py")):
            sys.path.insert(0, c)
            import redaction_gate  # noqa: E402  (path must be set first)
            return redaction_gate
    return None


def verbs_in(command: str) -> Set[str]:
    """The prose-carrying verbs present: a subset of {"git", "gh"}."""
    found: Set[str] = set()
    for m in PROSE_VERB_RE.finditer(command):
        found.add("git" if m.group(1) else "gh")
    return found


def read_body_file(path: str, cwd: str) -> str:
    """Contents of a body/notes file named on the command line; "" for stdin
    ("-"), a missing file or an unreadable one."""
    if path == "-":
        return ""
    full = path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _flag_value(token: str, flags: Set[str]) -> str:
    """The value of a ``--flag=value`` token when ``--flag`` is in ``flags``."""
    for flag in flags:
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return ""


def prose_from_command(command: str, cwd: str) -> str:
    """The prose a shell command is about to publish, joined by newlines.

    ``shlex.split`` keeps a ``$(cat <<'EOF' ...)`` body inside its quoted
    token, so heredoc commit messages are scanned with their delimiters as
    harmless extra lines. On a tokenizer error the raw command is returned.
    """
    verbs = verbs_in(command)
    if not verbs:
        return ""
    inline = set().union(*(INLINE_FLAGS[v] for v in verbs))
    files = set().union(*(FILE_FLAGS[v] for v in verbs))
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command
    texts: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok in inline and nxt is not None:
            texts.append(nxt)
            i += 2
            continue
        if tok in files and nxt is not None:
            texts.append(read_body_file(nxt, cwd))
            i += 2
            continue
        value = _flag_value(tok, inline)
        if value:
            texts.append(value)
        path = _flag_value(tok, files)
        if path:
            texts.append(read_body_file(path, cwd))
        i += 1
    return "\n".join(t for t in texts if t)


def prose_from_mcp(tool_input: dict) -> str:
    """The prose fields of a GitHub MCP call, joined by newlines."""
    parts = [tool_input.get(k) for k in MCP_PROSE_FIELDS]
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip())


def prose_of(event: dict) -> str:
    """Dispatch on the tool: "" when the event carries nothing to scan."""
    tool = event.get("tool_name", "")
    tin = event.get("tool_input") or {}
    if not isinstance(tin, dict):
        return ""
    if tool == "Bash":
        command = tin.get("command")
        if not isinstance(command, str):
            return ""
        return prose_from_command(command, str(event.get("cwd") or ""))
    if isinstance(tool, str) and tool.startswith(MCP_PREFIX):
        return prose_from_mcp(tin)
    return ""


def subject_of(event: dict) -> str:
    tool = event.get("tool_name", "")
    if tool == "Bash":
        return "the text this command is about to publish"
    return "the text this %s call is about to publish" % tool


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    text = prose_of(event)
    if not text.strip():
        return 0

    gate = _load_gate()
    if gate is None:
        return 0
    checker = gate.resolve_checker(os.path.dirname(os.path.abspath(__file__)))
    if not checker:
        return 0
    findings = gate.run_checker(checker, text)
    if not findings:
        return 0

    subject = subject_of(event)
    if gate.block_opt_in():
        print(gate.reason_text(findings, True, subject), file=sys.stderr)
        return 2
    if not gate.warn_silenced():
        print(gate.reason_text(findings, False, subject), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
