#!/usr/bin/env python3
"""stop-redaction-gate.py — Stop / SubagentStop hook: the redaction gate on
every message handed back.

The five prose-producing agents (paper-writer, professor, reviewer-academic,
memory-writer, ux-designer) carry a ``<redaction-gate>`` section that asks them
to run the eval in ``skills/writing/redaction.md`` on their own output before
returning it. A section in a prompt is advisory; what must happen every time
belongs in a hook. This hook is that enforcement point: it takes the final
assistant text of the turn (``last_assistant_message`` on Stop and
SubagentStop) and runs the mechanical half of the inventory over it through
``tools/redaction-checker.sh --stdin`` — the same detectors the pre-commit
hook runs on staged copy and ``pre-tool-redaction-gate.py`` runs on outbound
actions, so a message, a README and a commit body are held to one rule set.
The judgment half of the eval (nothing invented, every attribution sourced,
ends on a concrete point) cannot be grepped; when the mechanical half fires,
the hook's reason hands the whole eval back to the model to run on the rewrite.

Two-tier, mirroring stop-acceptance-gate.py and stop-zetetic-spine.py (a broad
check shipped to every session is report-only by default; blocking is opt-in,
product-safety lesson 2026-06-10):

* WARN (default): findings go to stderr, quoted line by line with the pattern
  name, and the turn ends. Suppress with REDACTION_STOP_WARN=off.
* BLOCK (opt-in): when ``.redaction-gate.json`` exists at the repo root, OR
  REDACTION_STOP_BLOCK=on, findings BLOCK the stop (decision:block, stdout,
  exit 0) so the model rewrites the message before it is returned. Loop-safe:
  a turn already in a forced continuation (``stop_hook_active``) is never
  blocked again; residual findings on the rewrite are still reported.

The mechanism (checker resolution, finding quotes, the opt-in) lives in
``tools/redaction_gate.py``, shared with the PreToolUse gate. A Stop hook must
not fail hard: a missing module or checker, a non-object payload, an empty
message or a checker error allows the stop (exit 0). The only thing that
blocks is a real finding under an active opt-in.
"""
import json
import os
import sys
from typing import List, NoReturn

_TOOL = "redaction-gate"

# Bounded reverse-tail read of the transcript, used ONLY when the harness did
# not hand over last_assistant_message. The final message of a turn is at the
# end of the file; 1 MiB covers a long message plus its tool_use rows.
# source: stop-zetetic-spine.py TAIL_BYTES rationale.
TAIL_BYTES = 1024 * 1024
SUBJECT = "the message being returned"


def _note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure (degrade open,
    never silently)."""
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


def _load_gate():
    """Import tools/redaction_gate.py from beside this hook or the plugin root.

    Returns None when no copy exists, so the caller can fail open the way it
    does for a missing checker (same resolution order as resolve_checker).
    """
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
    _note("tools/redaction_gate.py not found beside the hook; message not scanned",
          FileNotFoundError(candidates[0]))
    return None


def allow() -> NoReturn:
    sys.exit(0)


def block(reason: str) -> NoReturn:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def warn(reason: str) -> NoReturn:
    sys.stderr.write(reason + "\n")
    sys.exit(0)


def read_tail(path) -> str:
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


def last_message_from_transcript(path) -> str:
    """Fallback extraction of the final assistant text from the JSONL transcript.

    One API message is spread over several rows (one per content block) that
    share ``message.id``; the final text is every text block of the rows
    carrying the id of the last assistant row. Empty on any shape problem.
    """
    rows = []
    for line in read_tail(path).splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # the first line of a seek()ed tail is usually a fragment
        if isinstance(row, dict) and row.get("type") == "assistant":
            rows.append(row)
    if not rows:
        return ""
    last_id = (rows[-1].get("message") or {}).get("id")
    texts: List[str] = []
    for row in rows:
        msg = row.get("message") or {}
        if msg.get("id") != last_id:
            continue
        for blk in msg.get("content") or []:
            if isinstance(blk, dict) and blk.get("type") == "text" and blk.get("text"):
                texts.append(blk["text"])
    return "\n".join(texts)


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        allow()
    if not isinstance(data, dict):  # valid non-object JSON -> fail open
        allow()

    text = data.get("last_assistant_message")
    if not isinstance(text, str) or not text.strip():
        text = last_message_from_transcript(data.get("transcript_path"))
    if not text.strip():
        allow()

    gate = _load_gate()
    if gate is None:
        allow()
    checker = gate.resolve_checker(os.path.dirname(os.path.abspath(__file__)))
    if not checker:
        allow()
    findings = gate.run_checker(checker, text)
    if not findings:
        allow()

    if data.get("stop_hook_active"):  # forced continuation: report, never re-block
        warn(gate.reason_text(findings, False, SUBJECT))
    if gate.block_opt_in():
        block(gate.reason_text(findings, True, SUBJECT))
    if gate.warn_silenced():
        allow()
    warn(gate.reason_text(findings, False, SUBJECT))


if __name__ == "__main__":
    main()
