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
hook runs on staged copy, so a message and a README are held to one rule set.
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

A Stop hook must not fail hard: a missing checker, a non-object payload, an
empty message or a checker error allows the stop (exit 0). The only thing that
blocks is a real finding under an active opt-in.
"""
import json
import os
import re
import subprocess
import sys
from typing import List, NoReturn

_TOOL = "redaction-gate"

# Bounded reverse-tail read of the transcript, used ONLY when the harness did
# not hand over last_assistant_message. The final message of a turn is at the
# end of the file; 1 MiB covers a long message plus its tool_use rows.
# source: stop-zetetic-spine.py TAIL_BYTES rationale.
TAIL_BYTES = 1024 * 1024
# The checker is a line loop over one message; 30 s bounds a stuck interpreter.
# source: operational default, same order as run-python.sh's other stdin hooks.
CHECKER_TIMEOUT_S = 30
# Findings quoted in the block reason; the rest are counted, not listed, so the
# reason stays readable in the transcript. source: stop-acceptance-gate.py
# quotes unmet[:6] for the same reason.
MAX_QUOTED = 8

FINDING_RE = re.compile(r"^<stdin>:(\d+): ([A-Z_]+): (.*)$")


def _note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure (degrade open,
    never silently)."""
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


def allow() -> NoReturn:
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


def resolve_checker() -> str:
    """Path to the redaction checker that ships WITH this hook.

    The hook and the checker are one contract (``--stdin`` is the hook's
    interface), so the sibling copy is preferred over any repo-local
    ``tools/redaction-checker.sh``, which may predate the mode. Returns "" when
    no executable copy exists (fail-open upstream).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "tools", "redaction-checker.sh")]
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "tools", "redaction-checker.sh"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.access(c, os.X_OK):
            return c
    return ""


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


def run_checker(checker: str, text: str) -> List[str]:
    """Run the checker on the message; return its finding lines (possibly empty).

    ZETETIC_PROFILE is pinned to ``standard`` so the checker always exits 0 and
    reports: the WARN/BLOCK decision is this hook's, not the checker's.
    """
    env = dict(os.environ, ZETETIC_PROFILE="standard")
    try:
        proc = subprocess.run([checker, "--stdin"], input=text, capture_output=True,
                              text=True, timeout=CHECKER_TIMEOUT_S, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        _note("checker could not run; message not scanned", exc)
        return []
    if proc.returncode == 2:  # usage error: a checker without --stdin
        _note("checker rejected --stdin; message not scanned",
              RuntimeError(proc.stderr.strip()[:200]))
        return []
    return [ln for ln in proc.stdout.splitlines() if FINDING_RE.match(ln)]


def quote_findings(findings: List[str]) -> str:
    """'line N RULE: detail' for the first MAX_QUOTED findings, then a count."""
    parts = []
    for line in findings[:MAX_QUOTED]:
        m = FINDING_RE.match(line)
        if m:
            parts.append(f"line {m.group(1)} {m.group(2)}: {m.group(3)}")
    extra = len(findings) - MAX_QUOTED
    if extra > 0:
        parts.append(f"+{extra} more")
    return "; ".join(parts)


def reason_text(findings: List[str], blocking: bool) -> str:
    quoted = quote_findings(findings)
    head = ("Redaction gate: the message being returned carries %d candidate "
            "AI-writing pattern(s) from skills/writing/redaction.md: %s."
            % (len(findings), quoted))
    if blocking:
        return (head + " Rewrite it before returning: fix each quoted line, then run "
                "the skill's eval on the whole message (nothing invented; zero em "
                "dashes, antithesis constructions or triads; every attribution names "
                "its source or the claim is cut; ends on a concrete point, no recap "
                "and no closing offer). (.redaction-gate.json / REDACTION_STOP_BLOCK=on "
                "active; remove the marker or unset the variable to downgrade to a "
                "warning.)")
    return ("⚠ " + head + " (non-blocking; set REDACTION_STOP_BLOCK=on or "
            ".redaction-gate.json to enforce, REDACTION_STOP_WARN=off to silence.)")


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

    checker = resolve_checker()
    if not checker:
        allow()
    findings = run_checker(checker, text)
    if not findings:
        allow()

    if data.get("stop_hook_active"):  # forced continuation: report, never re-block
        warn(reason_text(findings, blocking=False))

    root = repo_root()
    blocking = (
        os.path.isfile(os.path.join(root, ".redaction-gate.json"))
        or os.environ.get("REDACTION_STOP_BLOCK", "").lower() == "on"
    )
    if blocking:
        block(reason_text(findings, blocking=True))
    if os.environ.get("REDACTION_STOP_WARN", "on").lower() == "off":
        allow()
    warn(reason_text(findings, blocking=False))


if __name__ == "__main__":
    main()
