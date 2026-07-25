#!/usr/bin/env python3
"""stop-context-guard.py — Stop hook: enforce the token-budget checkpoint protocol.

Contract (source of truth: agents/orchestrator.md <token-budget>):

  | Model              | Checkpoint (warn) | Hard cap (block) | Why                                  |
  |--------------------|-------------------|------------------|--------------------------------------|
  | Fable 5 / Mythos   | ~120K             | 160K             | 2x carrying rent + 2x resume penalty |
  | Opus 4.x           | ~180K             | 200K             | cost discipline (window is 1M)       |
  | Sonnet 4.6         | ~180K             | 200K             | cost discipline (window is 1M)       |
  | Haiku 4.5          | ~120K             | 170K             | 200K IS the window; leave ~30K of    |
  |                    |                   |                  | headroom for the checkpoint turn     |

  Thresholds are loaded from ~/.claude/ctxguard-thresholds.json (shared with
  the statusline so both layers stay on par by construction); the table above
  is the embedded fallback when the config is absent or malformed. First
  substring match against the lowercased model id wins.

  Context tokens are measured exactly as Claude Code's `used_percentage`:
      input_tokens + cache_creation_input_tokens + cache_read_input_tokens
  read from the most recent assistant turn in the transcript.

  Precondition:  invoked as a Stop hook with JSON on stdin containing
                 session_id, transcript_path, cwd, stop_hook_active.
  Postcondition:
    - below WARN            -> exit 0, no output, no side effects.
    - WARN <= ctx < HARD    -> write a free mechanical checkpoint stub (letta
                               summary schema) AND block the stop exactly once:
                               the model is instructed to spawn a budgeted
                               memory-writer subagent (<=16K-token context) that
                               persists the semantic checkpoint + cortex:remember
                               entries while headroom remains, then RESUME the
                               user's task in-session (reflection, not a stop).
    - ctx >= HARD           -> write the stub AND block the stop exactly once,
                               injecting the checkpoint-finalize procedure so the
                               model persists a scoped semantic checkpoint and
                               signals the user to clear + resume via recall.
                               Because WARN already ran the reflection, the hard
                               block is normally a formality, not a scramble.

  Checkpoint schema (letta-code summary schema): goals / file references
  (paths + line ranges) / errors and fixes / current state / next steps,
  <=500 words total, any quoted tool output clipped to 2,000 chars. Resume
  contract: read the checkpoint + ONE targeted recall; do NOT re-read files
  or docs the checkpoint already summarizes.

  Re-entrancy / loop safety:
    - if stop_hook_active is true, exit 0 (we are already in a forced continuation).
    - per-session state file records the highest level already fired; each level
      fires at most once per session, so the hard block cannot loop.

  Non-fatal by construction: any parse/IO error exits 0 (a Stop hook must never
  wedge the session). The statusline already provides the passive visual warning;
  this hook is the active enforcement layer.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import NoReturn

_TOOL = "ctxguard"

def _note(what: str, exc: BaseException) -> None:
    """One-line stderr note for a deliberately non-fatal failure.

    The hook still degrades open (that contract is what keeps a broken guard
    from breaking the session), but degrading SILENTLY is how a guard stops
    working without anyone noticing. stderr keeps the nominal path quiet while
    making the degraded path visible in hook logs.
    """
    print(f"[{_TOOL}] {what}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


# --- Thresholds (tokens) -----------------------------------------------------
# Single source of truth shared with statusline-command.sh. First substring
# match against the lowercased model id wins; "default" applies otherwise.
CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "ctxguard-thresholds.json"
)
FALLBACK_THRESHOLDS = {
    "models": [
        {"match": "fable",  "warn": 120_000, "hard": 160_000},
        {"match": "mythos", "warn": 120_000, "hard": 160_000},
        {"match": "haiku",  "warn": 120_000, "hard": 170_000},
        {"match": "sonnet", "warn": 180_000, "hard": 200_000},
        {"match": "opus",   "warn": 180_000, "hard": 200_000},
    ],
    "default": {"warn": 180_000, "hard": 200_000},
}


def _thresholds(model_id: str):
    """Return (warn, hard) for the model. Non-fatal: any config problem falls
    back to FALLBACK_THRESHOLDS; any malformed entry is skipped.

    Precondition:  model_id is a string or None.
    Postcondition: warn < hard, both positive ints.
    """
    table = FALLBACK_THRESHOLDS
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict) and isinstance(loaded.get("models"), list):
            table = loaded
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _note("ctxguard threshold config unreadable; using built-in defaults", exc)

    mid = (model_id or "").lower()
    chosen = table.get("default") or FALLBACK_THRESHOLDS["default"]
    for entry in table.get("models", []):
        try:
            if entry["match"] in mid:
                chosen = entry
                break
        except (KeyError, TypeError):
            continue
    try:
        warn, hard = int(chosen["warn"]), int(chosen["hard"])
        if 0 < warn < hard:
            return warn, hard
    except (KeyError, TypeError, ValueError) as exc:
        _note("ctxguard threshold entry malformed; using built-in defaults", exc)
    d = FALLBACK_THRESHOLDS["default"]
    return d["warn"], d["hard"]


STATE_DIR = "/tmp"
LEVEL_ORDER = {"none": 0, "warn": 1, "hard": 2}

# --- Bounded reverse-tail read parameters ------------------------------------
# Claude Code transcripts grow to 100MB–1GB in long sessions, and this hook
# fires on every Stop. Reading the whole file (readlines) is O(file size) in
# memory; we instead seek to the tail and scan backward.
#
# TAIL_CHUNK = 64 KiB (a power-of-two block multiple). Justification, measured
# on a real 24.5MB transcript at
#   ~/.claude/projects/-Users-cdeust-Developments-Cortex/<uuid>.jsonl :
#   - the last assistant `usage` record was 7,591 bytes from EOF;
#   - usage JSONL lines were min=1,016 / median=1,729 / max=32,769 bytes.
# A single 64 KiB tail read covers the last-usage offset ~8.6x over and the
# largest single usage line ~2x over, so one chunk suffices in practice.
# The usage record is rewritten on every assistant turn, so it is always near
# the end. Chunk-stepping with TAIL_MAX_BYTES is a hard safety bound, not a
# tuning knob.
TAIL_CHUNK = 64 * 1024          # 65536 bytes
TAIL_MAX_BYTES = 4 * 1024 * 1024  # cap total bytes scanned at 4 MiB


def _exit(payload=None) -> NoReturn:
    """Emit optional JSON to stdout and exit 0. A Stop hook must not fail hard.

    Annotated ``NoReturn`` deliberately: this never returns, and saying so is
    what lets a reader (and any analyser) see that the ``_exit()`` calls in
    ``main()`` are terminal. Without it, every branch that ends in ``_exit()``
    looks like a fall-through and the locals after it look possibly-unbound
    (CodeQL py/uninitialized-local-variable, 2 errors)."""
    if payload:
        sys.stdout.write(json.dumps(payload))
    sys.exit(0)


def _usage_from_line(line: str):
    """Parse one JSONL line; return (ctx, model) if it carries a positive
    assistant usage record, else None. Pure, no I/O."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    msg = obj.get("message") or {}
    usage = msg.get("usage")
    if not usage:
        return None
    ctx = (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("cache_creation_input_tokens", 0) or 0)
        + int(usage.get("cache_read_input_tokens", 0) or 0)
    )
    if ctx <= 0:
        return None
    return ctx, msg.get("model") or obj.get("model")


def _read_last_usage(transcript_path: str):
    """Return (context_tokens, model_id) from the most recent assistant usage,
    or (None, None) if unavailable.

    Precondition:  transcript_path is a path string (or None).
    Postcondition: returns (ctx, model) for the last line carrying a positive
                   usage record within the scanned tail, else (None, None).
                   On any missing/unreadable file or non-str path, returns
                   (None, None) — identical to the previous readlines() contract.

    Bounded reverse-tail read: seeks to max(0, size - TAIL_CHUNK) and scans the
    tail backward, stepping back chunk by chunk until a usage record is found
    or TAIL_MAX_BYTES have been scanned. Peak memory is O(TAIL_CHUNK), not
    O(file size). Decoded as UTF-8 with errors='replace' so a chunk boundary
    that splits a multi-byte sequence cannot raise.
    """
    try:
        size = os.stat(transcript_path).st_size
    except (OSError, TypeError, ValueError):
        return None, None
    if size == 0:
        return None, None

    try:
        fh = open(transcript_path, "rb")
    except (OSError, TypeError, ValueError):
        return None, None

    try:
        carry = ""          # bytes of a line split across the chunk boundary
        pos = size          # exclusive high-water mark of bytes not yet read
        scanned = 0
        while pos > 0 and scanned < TAIL_MAX_BYTES:
            read_size = min(TAIL_CHUNK, pos)
            pos -= read_size
            scanned += read_size
            fh.seek(pos)
            chunk = fh.read(read_size).decode("utf-8", errors="replace")
            # Prepend; carry holds the partial line that started inside this chunk.
            buf = chunk + carry
            # If we have not reached the start of the file, the first segment of
            # buf is a partial line (its true beginning is in an earlier chunk).
            # Hold it back as carry and scan only the complete lines after it.
            if pos > 0:
                nl = buf.find("\n")
                if nl == -1:
                    # No newline in the whole window yet: keep accumulating,
                    # but bound carry growth by the scan cap (handled by loop).
                    carry = buf
                    continue
                carry = buf[:nl]
                lines = buf[nl + 1:].split("\n")
            else:
                # Reached file start: buf begins at a real line boundary.
                carry = ""
                lines = buf.split("\n")
            for line in reversed(lines):
                hit = _usage_from_line(line)
                if hit is not None:
                    return hit
        # Cap reached or whole file consumed; check any final carried line.
        if carry:
            hit = _usage_from_line(carry)
            if hit is not None:
                return hit
        return None, None
    except OSError:
        return None, None
    finally:
        fh.close()


def _git(cwd: str, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "-c", "core.useBuiltinFSMonitor=false", *args],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _write_stub(session_id: str, cwd: str, ctx: int, model_id: str, level: str) -> str:
    """Capture mechanical session state for free. Returns the stub path (or '')."""
    root = os.path.join(os.path.expanduser("~"), ".claude", "memories", "checkpoints")
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return ""

    branch = _git(cwd, "symbolic-ref", "--short", "HEAD") or _git(cwd, "rev-parse", "--short", "HEAD")
    last_commit = _git(cwd, "log", "-1", "--oneline")
    modified = _git(cwd, "status", "--porcelain")
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    stub = f"""---
description: "Auto-checkpoint ({level}) at {ctx:,} tokens — session {session_id[:8]} on {branch or 'unknown branch'}"
---
## Auto-checkpoint stub ({level}) — {iso}

> Mechanical state captured for free by stop-context-guard at {ctx:,} context
> tokens (model: {model_id or 'unknown'}). The semantic fields below follow the
> letta summary schema. Budget: <=500 words total across all sections; clip any
> quoted tool output to 2,000 chars.

### Goals
<to be filled: what this session is trying to achieve, in priority order>

### File references
(paths + line ranges the resumed session will need; seeded from git status —
replace with the load-bearing files and add `path:start-end` line ranges)
{os.linesep.join('- ' + l.strip() for l in modified.splitlines()) if modified else '- (working tree clean)'}

### Errors and fixes
<to be filled: each error hit this session and how it was fixed or worked around>

### Current state
- session_id: {session_id}
- model: {model_id or 'unknown'} · context tokens at trigger: {ctx:,}
- working dir: {cwd}
- branch: {branch or '(unknown)'} · last commit: {last_commit or '(none)'}
<to be filled: one paragraph — where the work stands right now>

### Next steps
<to be filled: exact ordered actions for the resumed session; first one must be
executable without re-deriving anything>

### Resume contract
Read this checkpoint + ONE targeted, agent_topic-scoped cortex:recall. Do NOT
re-read files or docs this checkpoint already summarizes — trust the file
references above and verify with targeted Reads only when editing.
"""
    per_session = os.path.join(root, f"{session_id}.md")
    latest = os.path.join(root, "latest.md")
    try:
        with open(per_session, "w", encoding="utf-8") as fh:
            fh.write(stub)
        with open(latest, "w", encoding="utf-8") as fh:
            fh.write(stub)
    except OSError:
        return ""
    return per_session


def _load_level(session_id: str) -> str:
    path = os.path.join(STATE_DIR, f"zetetic-ctxguard-{session_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("level", "none")
    except (OSError, json.JSONDecodeError):
        return "none"


def _save_level(session_id: str, level: str) -> None:
    path = os.path.join(STATE_DIR, f"zetetic-ctxguard-{session_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"level": level}, fh)
    except OSError as exc:
        _note("ctxguard level-state write failed; the guard may re-fire this session", exc)


SCHEMA = (
    "goals / file references (paths + line ranges) / errors and fixes / "
    "current state / next steps — <=500 words total, quoted tool outputs "
    "clipped to 2,000 chars"
)


def _warn_reason(ctx: int, stub_path: str, warn: int, hard: int) -> str:
    return (
        f"⚠ CHECKPOINT THRESHOLD — {ctx:,} input tokens "
        f"(≥ {warn:,} for this model; hard stop at {hard:,}).\n"
        f"This is a reflection pause, NOT the end of the session. While you still "
        f"have headroom, persist the semantic checkpoint via a budgeted subagent, "
        f"then resume the user's task:\n\n"
        f"1. Distill the session into the letta summary schema ({SCHEMA}).\n"
        f"2. Spawn the memory-writer subagent (Agent tool, subagent_type "
        f"\"memory-writer\", model haiku, ≤16K-token context). Pass it: your "
        f"distilled summary, your memory scope + MEMORY_AGENT_ID, and the stub "
        f"path {stub_path or 'n/a'}. It merges the summary into the stub schema at "
        f"/memories/<your-scope>/checkpoint.md and stores durable WHY-level facts "
        f"via cortex:remember (agent_topic-scoped). Do not write the checkpoint "
        f"yourself unless the spawn fails.\n"
        f"3. CONTINUE the user's task in this session. The hard cap at {hard:,} "
        f"still applies; thanks to this reflection it should be a formality."
    )


def _block_reason(ctx: int, stub_path: str, hard: int) -> str:
    return (
        f"⚠ CONTEXT SOFT CAP REACHED — {ctx:,} input tokens "
        f"(≥ {hard:,} session budget for this model).\n"
        f"Continuing in this session now risks context poisoning, quota burn, and "
        f"escalating per-turn cost. Execute the checkpoint protocol before yielding:\n\n"
        f"1. Write (or update) your scoped semantic checkpoint with the memory tool:\n"
        f"   MEMORY_AGENT_ID=<your-scope> tools/memory-tool.sh create "
        f"/memories/<your-scope>/checkpoint.md \"<{SCHEMA}>\"\n"
        f"   (Mechanical state was already captured for free at: {stub_path or 'n/a'} — "
        f"merge into its schema; if the WARN-time memory-writer already wrote the "
        f"checkpoint, update only what changed since.)\n"
        f"2. If important decisions are not yet durable, persist them now "
        f"(cortex:remember, scoped to your agent_topic).\n"
        f"3. End your response with exactly:\n"
        f"   CHECKPOINT — context cleared.\n"
        f"   Resume from: /memories/<your-scope>/checkpoint.md\n"
        f"   Next action: <exact first thing to do on restart>\n"
        f"Then instruct the user to run /clear and resume. Resume contract: the "
        f"next session reads the checkpoint + ONE targeted recall — it must NOT "
        f"re-read files or docs the checkpoint already summarizes.\n"
        f"Do NOT start new substantive work in this session."
    )


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _exit()

    # Valid JSON that is not an object (e.g. a bare number, string, list, or
    # null) parses without error but has no .get(); treating it as a missing
    # payload preserves the fail-open contract (parse/shape problems exit 0).
    if not isinstance(data, dict):
        _exit()

    # Loop guard: if we already forced a continuation, do not act again.
    if data.get("stop_hook_active"):
        _exit()

    session_id = data.get("session_id") or "unknown"
    transcript_path = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()

    ctx, model_id = _read_last_usage(transcript_path)
    if ctx is None:
        _exit()

    warn, hard = _thresholds(model_id)
    if ctx >= hard:
        level = "hard"
    elif ctx >= warn:
        level = "warn"
    else:
        _exit()

    prev = _load_level(session_id)
    # Only act when crossing UP into a not-yet-fired level.
    if LEVEL_ORDER[level] <= LEVEL_ORDER[prev]:
        _exit()

    stub_path = _write_stub(session_id, cwd, ctx, model_id, level)
    _save_level(session_id, level)

    if level == "hard":
        _exit({
            "decision": "block",
            "reason": _block_reason(ctx, stub_path, hard),
            "systemMessage": (
                f"[context-guard] {ctx:,} tokens ≥ {hard:,} soft cap "
                f"({model_id or 'model'}) — forcing a checkpoint before the "
                f"session continues."
            ),
        })
    else:  # warn — one-time reflection block: persist memory while headroom remains
        _exit({
            "decision": "block",
            "reason": _warn_reason(ctx, stub_path, warn, hard),
            "systemMessage": (
                f"[context-guard] {ctx:,} tokens ≥ {warn:,} checkpoint threshold "
                f"({(model_id or 'model')}) — spawning a budgeted memory-writer to "
                f"persist the semantic checkpoint, then the session continues. "
                f"Mechanical stub: {stub_path or 'n/a'}. Hard stop at {hard:,}."
            ),
        })


if __name__ == "__main__":
    main()
