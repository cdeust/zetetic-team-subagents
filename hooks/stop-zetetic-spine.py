#!/usr/bin/env python3
"""stop-zetetic-spine.py — Stop hook: the turn-level zetetic-spine gate.

Every agent carries the zetetic spine inline (recall -> evidence/sources ->
adversarial-verify -> remember). This hook is the *hard, proportional* layer:
when a turn produced changes (Edit/Write/...) with no sign that the spine's
recall/evidence beats ran, it surfaces the gap.

Two-tier, mirroring stop-acceptance-gate.py and the product-safety lesson it
encodes (a broad check shipped to every session must be report-only by default;
blocking is opt-in, never the default — encoded 2026-06-10):

* WARN (default): report-only, ONE-TIME per session. When the turn made changes
  and the scanned transcript tail shows no recall / memory / web-evidence
  activity, emit a non-blocking reminder (stderr) and never fire again this
  session. Suppress entirely with ZETETIC_SPINE_WARN=off.
* BLOCK (opt-in): when `.zetetic-spine.json` exists at the repo root, OR
  ZETETIC_SPINE_BLOCK=on, the same condition BLOCKS the turn (decision:block,
  stdout, exit 0) until the spine is satisfied. Intended for autonomous runs
  that opted into hard gating. Loop-safe via stop_hook_active; Claude Code ends
  the turn after 8 consecutive blocks, bounding the loop.

A Stop hook must not fail hard: any parse/IO/shape problem allows the stop
(exit 0). The only thing that blocks is an unmet spine under an active marker.
Rationale: memory/ADR-003-zetetic-spine-enforcement.md.
"""
import json
import os
import re
import subprocess
import sys
from typing import NoReturn

_TOOL = "zetetic-spine"

def _note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure.

    The hook still degrades open (that contract is what keeps a broken guard
    from breaking the session), but degrading SILENTLY is how a guard stops
    working without anyone noticing. stderr keeps the nominal path quiet while
    making the degraded path visible in hook logs.
    """
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


STATE_DIR = "/tmp"
# Bounded reverse-tail read of the transcript. The spine's beats normally fall
# within a recent window; a 1 MiB cap keeps the hook cheap on multi-100MB
# transcripts. source: stop-context-guard.py tail-read rationale (64 KiB there
# is for a single usage line; the spine needs a wider window for tool activity).
TAIL_BYTES = 1024 * 1024

# Tool-use shapes (tolerant of JSON whitespace). Changes = claim/state-producing
# tool calls; spine-evidence = recall / memory / web-evidence activity.
CHANGE_RE = re.compile(r'"name"\s*:\s*"(Edit|Write|MultiEdit|NotebookEdit)"')
EVIDENCE_RE = re.compile(
    r'"name"\s*:\s*"(mcp__plugin_hypermnesia-mcp_cortex__recall'
    r'|mcp__plugin_hypermnesia-mcp_cortex__unified_search'
    r'|mcp__plugin_hypermnesia-mcp_cortex__navigate_memory'
    r'|WebSearch|WebFetch)"'
)
# memory-tool.sh view/search appears inside a Bash tool_input command string.
MEMORY_CMD_RE = re.compile(r"memory-tool\.sh\s+(view|search)")


def allow() -> NoReturn:
    """A Stop hook signals 'no objection' by exiting 0 silently.

    ``NoReturn`` for the same reason as ctxguard's ``_exit()``: these end
    branches, and stating that control does not fall through is what keeps a
    reader (and any analyser) from treating the following code as reachable.
    """
    sys.exit(0)


def block(reason: str) -> NoReturn:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def warn(reason: str) -> NoReturn:
    sys.stderr.write(reason + "\n")
    sys.exit(0)


def repo_root() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return os.getcwd()
    return out or os.getcwd()


def read_tail(path: str) -> str:
    """Return up to TAIL_BYTES of the transcript's end, decoded leniently.
    Empty string on any problem (fail-open upstream)."""
    if not path or not isinstance(path, str):
        return ""
    try:
        size = os.stat(path).st_size
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def spine_unmet(tail: str) -> bool:
    """True iff the tail shows changes but no recall/memory/web-evidence — the
    signal that the spine's recall/evidence beats were skipped this window."""
    if not CHANGE_RE.search(tail):
        return False  # no claim/state change this window — spine not triggered
    if EVIDENCE_RE.search(tail) or MEMORY_CMD_RE.search(tail):
        return False  # evidence/recall activity present — assume spine engaged
    return True


def already_warned(session_id: str) -> bool:
    return os.path.exists(os.path.join(STATE_DIR, f"zetetic-spine-{session_id}.json"))


def mark_warned(session_id: str) -> None:
    try:
        with open(os.path.join(STATE_DIR, f"zetetic-spine-{session_id}.json"), "w") as fh:
            json.dump({"warned": True}, fh)
    except OSError as exc:
        _note("spine warn-state write failed; the reminder may repeat", exc)


REASON = (
    "⚠ Zetetic spine: this turn changed state (Edit/Write) with no recall or "
    "evidence activity in the recent transcript. Before ending, confirm the "
    "spine ran: recall (cortex:recall scoped to your agent_topic) → "
    "evidence/sources (every claim cited; no source → \"I don't know\") → "
    "adversarial-verify (a test that catches the error if it exists) → remember "
    "(persist WHY-level outcomes). Full procedure: "
    "~/.claude/rules/agent-reference/zetetic-spine.md."
)


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        allow()
    if not isinstance(data, dict):  # valid non-object JSON -> fail open
        allow()
    if data.get("stop_hook_active"):  # already in a forced continuation -> no loop
        allow()

    session_id = data.get("session_id") or "unknown"
    tail = read_tail(data.get("transcript_path"))
    if not spine_unmet(tail):
        allow()

    root = repo_root()
    blocking = (
        os.path.isfile(os.path.join(root, ".zetetic-spine.json"))
        or os.environ.get("ZETETIC_SPINE_BLOCK", "").lower() == "on"
    )
    if blocking:
        block(REASON + " (.zetetic-spine.json active — run the spine to clear "
              "this gate, or remove the marker to downgrade to a warning.)")

    # WARN tier (default) — report-only, one-time per session.
    if os.environ.get("ZETETIC_SPINE_WARN", "on").lower() == "off":
        allow()
    if already_warned(session_id):
        allow()
    mark_warned(session_id)
    warn(REASON + " (non-blocking; set .zetetic-spine.json to enforce, or "
         "ZETETIC_SPINE_WARN=off to silence.)")


if __name__ == "__main__":
    main()
