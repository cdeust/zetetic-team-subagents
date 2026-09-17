#!/usr/bin/env python3
"""redaction_gate.py — the mechanism shared by the two redaction hooks.

``hooks/stop-redaction-gate.py`` (every returned message) and
``hooks/pre-tool-redaction-gate.py`` (every outbound action that carries prose:
commit messages, PR and issue bodies, GitHub comments) hold text to one rule
set through one code path: run ``tools/redaction-checker.sh --stdin``, quote
each finding with its line number and pattern name, and read the WARN/BLOCK
opt-in from one place (``REDACTION_STOP_BLOCK=on`` or a ``.redaction-gate.json``
marker at the repo root). The hooks own their event contract (payload shape,
exit code, loop safety); this module owns the mechanism, so the two gates
cannot drift apart (coding-standards.md §1.2, §3.3).

Every function here degrades open: a checker that cannot run, a subprocess
error or a missing git binary yields "no findings" plus a stderr note, never an
exception, because a hook that crashes enforces nothing and hides why.
"""
import os
import re
import subprocess
import sys
from typing import List

_TOOL = "redaction-gate"

# The checker is a line loop over one text; 30 s bounds a stuck interpreter.
# source: operational default, same order as run-python.sh's other stdin hooks.
CHECKER_TIMEOUT_S = 30
# Findings quoted in a reason; the rest are counted, not listed, so the reason
# stays readable in the transcript. source: stop-acceptance-gate.py quotes
# unmet[:6] for the same reason.
MAX_QUOTED = 8
# The checker's ``--stdin`` finding line: ``<stdin>:LINE: RULE: detail``.
FINDING_RE = re.compile(r"^<stdin>:(\d+): ([A-Z_]+): (.*)$")

MARKER_FILE = ".redaction-gate.json"
BLOCK_ENV = "REDACTION_STOP_BLOCK"
WARN_ENV = "REDACTION_STOP_WARN"


def note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure."""
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


def repo_root() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return os.getcwd()
    return out or os.getcwd()


def resolve_checker(anchor_dir: str) -> str:
    """Path to the redaction checker that ships WITH the calling hook.

    The hook and the checker are one contract (``--stdin`` is the hook's
    interface), so the copy beside the hook is preferred over any repo-local
    ``tools/redaction-checker.sh``, which may predate the mode. Returns "" when
    no executable copy exists (fail-open upstream).
    """
    candidates = [os.path.join(anchor_dir, "..", "tools", "redaction-checker.sh")]
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "tools", "redaction-checker.sh"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.access(c, os.X_OK):
            return c
    return ""


def run_checker(checker: str, text: str) -> List[str]:
    """Run the checker on ``text``; return its finding lines (possibly empty).

    ZETETIC_PROFILE is pinned to ``standard`` so the checker always exits 0 and
    reports: the WARN/BLOCK decision belongs to the hook, not the checker.
    """
    env = dict(os.environ, ZETETIC_PROFILE="standard")
    try:
        proc = subprocess.run([checker, "--stdin"], input=text, capture_output=True,
                              text=True, timeout=CHECKER_TIMEOUT_S, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        note("checker could not run; text not scanned", exc)
        return []
    if proc.returncode == 2:  # usage error: a checker without --stdin
        note("checker rejected --stdin; text not scanned",
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


def block_opt_in() -> bool:
    """True when the user asked findings to block: the env switch, or the
    marker file at the root of the repository the hook runs in."""
    return (os.environ.get(BLOCK_ENV, "").lower() == "on"
            or os.path.isfile(os.path.join(repo_root(), MARKER_FILE)))


def warn_silenced() -> bool:
    return os.environ.get(WARN_ENV, "on").lower() == "off"


def reason_text(findings: List[str], blocking: bool, subject: str) -> str:
    """The message a hook reports. ``subject`` names what was scanned, e.g.
    "the message being returned" or "the commit message about to be sent"."""
    head = ("Redaction gate: %s carries %d candidate AI-writing pattern(s) from "
            "skills/writing/redaction.md: %s."
            % (subject, len(findings), quote_findings(findings)))
    if blocking:
        return (head + " Rewrite it before sending: fix each quoted line, then run "
                "the skill's eval on the whole text (nothing invented; zero em "
                "dashes, antithesis constructions or triads; no bold label "
                "bullets; every attribution names its source or the claim is cut; "
                "ends on a concrete point, no recap and no closing offer). "
                "(%s / %s=on active; remove the marker or unset the variable to "
                "downgrade to a warning.)" % (MARKER_FILE, BLOCK_ENV))
    return ("⚠ " + head + " (non-blocking; set %s=on or %s to enforce, %s=off to "
            "silence.)" % (BLOCK_ENV, MARKER_FILE, WARN_ENV))
