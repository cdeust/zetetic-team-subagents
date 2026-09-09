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

  Context tokens are read from the most recent assistant turn by
  tools/transcript_scan.py, which owns the `used_percentage` formula.

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
from typing import NamedTuple, NoReturn

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


class Trigger(NamedTuple):
    """The five facts that describe one firing: who, where, how much, on what
    model, at which level. They are read together by the stub writer, the state
    record and the block builder, so they travel as one value rather than as
    five parallel parameters."""
    session_id: str
    cwd: str
    ctx: int
    model_id: str
    level: str


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


def _load_scan():
    """Import tools/transcript_scan.py from beside this hook or the plugin root.

    Same resolution order as stop-redaction-gate's _load_gate. Returns None
    when no copy exists; the caller then exits 0, which is this hook's
    standing contract for anything it cannot measure (see module docstring:
    non-fatal by construction).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "tools")]
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "tools"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(os.path.join(c, "transcript_scan.py")):
            sys.path.insert(0, c)
            import transcript_scan  # noqa: E402  (path must be set first)
            return transcript_scan
    _note("tools/transcript_scan.py not found beside the hook; context not measured",
          FileNotFoundError(candidates[0]))
    return None


def _read_last_usage(transcript_path: str):
    """(context_tokens, model_id) at the most recent assistant turn, or
    (None, None) when the transcript is unusable or the scanner is missing."""
    scan = _load_scan()
    if scan is None:
        return None, None
    return scan.read_last_usage(transcript_path)


def _has_activity_since(transcript_path: str, since_offset: int) -> bool:
    """True if a tool_use block appears at or after `since_offset`. Fail-open
    (True) when the scan cannot conclude, including a missing scanner: the
    cost of a redundant checkpoint is far below that of a dropped one."""
    scan = _load_scan()
    if scan is None:
        return True
    return scan.has_activity_since(transcript_path, since_offset, _note)


def _git(cwd: str, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "-c", "core.useBuiltinFSMonitor=false", *args],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _write_stub(trigger: Trigger) -> str:
    """Capture mechanical session state for free. Returns the stub path (or '')."""
    session_id, cwd, ctx, model_id, level = trigger
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


def _load_state(session_id: str) -> dict:
    """Return the persisted state dict for this session, defaulting to
    {"level": "none"} on any missing/malformed/legacy file. Additive schema:
    level (str), initial_ctx/last_fire_ctx (int), last_fire_offset (int,
    transcript byte offset at the most recent real fire -- the baseline for
    the next _has_activity_since check), fired_at (ISO str). Telemetry
    fields are for future replay/ablation only; they gate nothing yet."""
    path = os.path.join(STATE_DIR, f"zetetic-ctxguard-{session_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "level" in data:
            return data
    except (OSError, json.JSONDecodeError):
        # Deliberate: an unreadable, absent or legacy state file is not an
        # error here. The guard's contract is to degrade to the "none" level
        # and re-derive from the transcript, never to fail the Stop hook and
        # block the session on its own bookkeeping.
        pass
    return {"level": "none"}


def _save_state(session_id: str, state: dict) -> None:
    path = os.path.join(STATE_DIR, f"zetetic-ctxguard-{session_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
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
        f"have headroom, persist the semantic checkpoint directly (cheapest path — "
        f"a few hundred tokens), then resume the user's task:\n\n"
        f"1. Distill the session into the letta summary schema ({SCHEMA}).\n"
        f"2. Write it directly: MEMORY_AGENT_ID=<your-scope> tools/memory-tool.sh "
        f"rethink /memories/<your-scope>/checkpoint.md \"<distilled summary>\", plus "
        f"one cortex:remember call per WHY-level fact (agent_topic-scoped) — or, if "
        f"no scoped store, fill the stub at {stub_path or 'n/a'} in place. Only "
        f"spawn the memory-writer subagent (Agent tool, subagent_type "
        f"\"memory-writer\") instead if you are yourself close to the hard cap and "
        f"want to preserve your own remaining headroom, or if the direct write "
        f"fails.\n"
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


def _read_payload():
    """Parse the hook payload from stdin, or None when it is unusable.

    Split out of ``main()`` so the local is ALWAYS bound. Inline, the value was
    assigned in the ``try`` and the ``except`` ended in ``_exit()``; that is
    correct at runtime but only because ``_exit()`` never returns, which no
    intraprocedural analyser can see (the ``NoReturn`` annotation states it for
    a reader and for a type checker, but CodeQL's py/uninitialized-local-
    variable does not consult annotations — it kept flagging the use below).
    Returning a value on every path makes the property structural instead of
    inferred, which is the honest fix: nothing is suppressed and there is no
    path where the caller reads an unbound name.
    """
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return None


def _level_for(ctx: int, warn: int, hard: int):
    """Threshold band for ``ctx``: "hard", "warn", or None when below both.

    Same reason as ``_read_payload``: every path returns, so the caller's local
    is bound before it is read.
    """
    if ctx >= hard:
        return "hard"
    if ctx >= warn:
        return "warn"
    return None


def _gate(data: dict):
    """Decide whether this Stop should fire, and at which level.

    Returns (trigger, warn, hard, since_offset, state) when it should, or None
    when it should not — every "not" is a silent exit 0, this hook's standing
    contract. Split out of ``main()`` so the decision is one readable sequence
    of guards and the caller is left with the side effects only.
    """
    # Loop guard: if we already forced a continuation, do not act again.
    if data.get("stop_hook_active"):
        return None

    session_id = data.get("session_id") or "unknown"
    transcript_path = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()

    ctx, model_id = _read_last_usage(transcript_path)
    if ctx is None:
        return None

    warn, hard = _thresholds(model_id)
    level = _level_for(ctx, warn, hard)
    if level is None:
        return None

    state = _load_state(session_id)
    # Only act when crossing UP into a not-yet-fired level.
    if LEVEL_ORDER[level] <= LEVEL_ORDER[state.get("level", "none")]:
        return None

    # Activity gate: skip silently if nothing checkpointable happened since
    # the last fire (or session start). The byte offset is only meaningful
    # against the SAME growing transcript file -- if transcript_path changed
    # since the last fire (rotation, compaction, a different session reusing
    # this session_id), a stale offset compared against an unrelated file is
    # worse than useless, so it is only trusted when the path matches.
    # Does NOT advance level/offset/path on skip, so the next Stop re-checks
    # from the same baseline and fires as soon as real activity appears --
    # never permanently silenced.
    since_offset = (
        state.get("last_fire_offset", 0)
        if state.get("transcript_path") == transcript_path else 0
    )
    if not _has_activity_since(transcript_path, since_offset):
        return None

    return Trigger(session_id, cwd, ctx, model_id, level), warn, hard, since_offset, state


def _record_fire(trigger: Trigger, data: dict, since_offset: int, state: dict) -> None:
    """Persist the level/offset baseline the next Stop compares against."""
    try:
        new_offset = os.stat(data.get("transcript_path")).st_size
    except (OSError, TypeError, ValueError):
        new_offset = since_offset
    _save_state(trigger.session_id, {
        "level": trigger.level,
        "initial_ctx": state.get("initial_ctx") or trigger.ctx,
        "last_fire_ctx": trigger.ctx,
        "last_fire_offset": new_offset,
        "transcript_path": data.get("transcript_path"),
        "fired_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def _block(trigger: Trigger, stub_path: str, warn: int, hard: int) -> dict:
    """The Stop payload for a firing. At "warn" this is a one-time reflection
    block (persist memory while headroom remains, then continue); at "hard" it
    forces the checkpoint before the session may go on."""
    if trigger.level == "hard":
        reason = _block_reason(trigger.ctx, stub_path, hard)
        message = (
            f"[context-guard] {trigger.ctx:,} tokens ≥ {hard:,} soft cap "
            f"({trigger.model_id or 'model'}) — forcing a checkpoint before the "
            f"session continues."
        )
    else:
        reason = _warn_reason(trigger.ctx, stub_path, warn, hard)
        message = (
            f"[context-guard] {trigger.ctx:,} tokens ≥ {warn:,} checkpoint threshold "
            f"({trigger.model_id or 'model'}) — spawning a budgeted memory-writer to "
            f"persist the semantic checkpoint, then the session continues. "
            f"Mechanical stub: {stub_path or 'n/a'}. Hard stop at {hard:,}."
        )
    return {"decision": "block", "reason": reason, "systemMessage": message}


def main():
    data = _read_payload()

    # Valid JSON that is not an object (e.g. a bare number, string, list, or
    # null) parses without error but has no .get(); treating it as a missing
    # payload preserves the fail-open contract (parse/shape problems exit 0).
    # `None` from a parse failure lands here too — same contract, one check.
    if not isinstance(data, dict):
        _exit()

    decision = _gate(data)
    if decision is None:
        _exit()
    trigger, warn, hard, since_offset, state = decision

    stub_path = _write_stub(trigger)
    _record_fire(trigger, data, since_offset, state)

    _exit(_block(trigger, stub_path, warn, hard))


if __name__ == "__main__":
    main()
