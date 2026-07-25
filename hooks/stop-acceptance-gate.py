#!/usr/bin/env python3
"""stop-acceptance-gate.py — Stop hook: the real-exec acceptance gate.

This hook runs the REAL acceptance gate (``tools/acceptance-gate.sh``) as a genuine
subprocess and reports its real exit code — the deterministic, external stop-gate
the Claude Code best-practices guide recommends ("a Stop hook runs your check as a
script and blocks the turn from ending until it passes",
code.claude.com/docs/en/best-practices). The model does not report the verdict; the
kernel does, via the process exit code.

Two-tier, mirroring the mutation policy (rules/coding-standards.md §12.5):

* WARN (default): when there are uncommitted changes and NO ``.abl-gate.json``
  marker, run the gate and, if it is red, SURFACE the unmet gates as a
  non-blocking warning (stderr) — then allow the turn to end. This makes the gate
  visible by default without ever freezing an ordinary session. A heavy/broad
  check that ships to every session must be report-only by default (product-safety
  lesson 2026-06-10); blocking is opt-in, never the default.
* BLOCK (opt-in): when ``.abl-gate.json`` exists (an autonomous build run), a red
  gate BLOCKS the turn until it passes. Marker schema (gitignored):
  {config?, diff_base?, diff_head?}.

WARN runs only when ``git status`` shows changes, so pure chat turns stay cheap, and
is fully suppressible with ``ABL_STOP_WARN=off``. A Stop hook must not fail hard:
any error, un-runnable gate, or timeout allows the stop (exit 0). The only thing
that blocks is a real non-zero exit under an active marker. Claude Code ends the
turn after 8 consecutive blocks, bounding the loop.
"""
import json
import os
import subprocess
import sys

_TOOL = "acceptance-gate"

def _note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure.

    The hook still degrades open (that contract is what keeps a broken guard
    from breaking the session), but degrading SILENTLY is how a guard stops
    working without anyone noticing. stderr keeps the nominal path quiet while
    making the degraded path visible in hook logs.
    """
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


# The full gate runs test suites + the zetetic checker; 15 min bounds a stuck gate.
# source: operational default (>= acceptance_gate.py per-gate ceiling x a few gates).
GATE_TIMEOUT_S = 900
# WARN runs opportunistically at turn end; cap it short so a slow suite degrades to
# "no warning" rather than stalling an ordinary session. source: operational default.
WARN_TIMEOUT_S = 120


def allow() -> None:
    """Let the turn end. A Stop hook signals 'no objection' by exiting 0 silently."""
    sys.exit(0)


def block(reason: str) -> None:
    """Block the stop so the model keeps working until the real gate passes."""
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def warn(reason: str) -> None:
    """Surface the gate result without blocking (stderr shows in the transcript)."""
    sys.stderr.write(reason + "\n")
    sys.exit(0)


def repo_root() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return os.getcwd()
    return out or os.getcwd()


def has_changes(root: str) -> bool:
    """True iff the working tree has uncommitted changes — the only case WARN runs."""
    try:
        out = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


def gate_args(root: str, cfg: dict) -> list:
    """Build the acceptance-gate.sh argv from a marker config (empty cfg -> defaults)."""
    gate = os.path.join(root, "tools", "acceptance-gate.sh")
    args = [gate, "--config",
            os.path.join(root, cfg.get("config", "memory/acceptance-gates.loop.yaml"))]
    base, head = cfg.get("diff_base"), cfg.get("diff_head")
    if base and head:
        args += ["--diff-base", base, "--diff-head", head]
    return args


def run_gate(args: list, root: str, timeout: int):
    """Run the gate; return (returncode, unmet[]) or None when it cannot be run."""
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    unmet = []
    try:
        unmet = json.loads(proc.stdout).get("unmet", [])
    except ValueError as exc:
        _note("acceptance-gate output was not JSON; treating as no unmet criteria", exc)
    return proc.returncode, unmet


def verdict_reason(prefix: str, rc: int, unmet: list) -> str:
    reason = "%s (tools/acceptance-gate.sh exit %d)." % (prefix, rc)
    if unmet:
        reason += " Unmet: " + "; ".join(unmet[:6])
    return reason


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        allow()
    if not isinstance(payload, dict):  # valid non-object JSON (e.g. []) -> fail open
        allow()
    if payload.get("stop_hook_active"):  # already in a forced continuation -> do not loop
        allow()

    root = repo_root()
    gate = os.path.join(root, "tools", "acceptance-gate.sh")
    if not os.access(gate, os.X_OK):
        allow()

    marker = os.path.join(root, ".abl-gate.json")
    if os.path.isfile(marker):
        # BLOCK tier — an autonomous build run opted in to hard gating.
        try:
            with open(marker, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            allow()
        if not isinstance(cfg, dict):  # hand-edited non-object marker -> fail open
            allow()
        result = run_gate(gate_args(root, cfg), root, GATE_TIMEOUT_S)
        if result is None or result[0] == 0:
            allow()
        block(verdict_reason("Acceptance gate is not green; keep working until it passes",
                             result[0], result[1]))

    # WARN tier (default) — report-only, and only when there is something to check.
    if os.environ.get("ABL_STOP_WARN", "on").lower() == "off":
        allow()
    if not has_changes(root):
        allow()
    # WARN checks the committed BASE gate set, not the autonomous-loop variant.
    result = run_gate(gate_args(root, {"config": "memory/acceptance-gates.yaml"}),
                      root, WARN_TIMEOUT_S)
    if result is None or result[0] == 0:
        allow()
    warn(verdict_reason("⚠ Acceptance gate is RED (non-blocking warning)",
                        result[0], result[1])
         + " — set .abl-gate.json to make this blocking, or ABL_STOP_WARN=off to silence.")


if __name__ == "__main__":
    main()
