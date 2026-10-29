#!/usr/bin/env python3
"""stop-context-guard.py — Stop hook: enforce the token-budget checkpoint protocol.

Token-budget contract (the table below is the source of truth; the per-model
  values are loaded from ~/.claude/ctxguard-thresholds.json):

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
    - WARN <= ctx < HARD    -> the hook itself writes a filled checkpoint (see below)
                               and emits a non-blocking systemMessage naming it. No
                               subagent is spawned and the turn is not blocked.
    - ctx >= HARD           -> same checkpoint, plus a systemMessage telling the user
                               to /clear and resume from the file. Not blocking either:
                               the checkpoint is already durable.

  Checkpoint (letta-code summary schema): goals / file references / errors and
  fixes / current state / next steps. Owner decision 2026-10-21: no agent writes
  it. tools/checkpoint_summary.py measures every field from the transcript named
  in the hook input and from git (last user requests, files edited, commands
  run, tool errors, last assistant message, open TODOs); a field it cannot
  measure reads "(none found)". Quoted tool output is clipped. Resume
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

import importlib
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
    model, at which level. They are read together by the checkpoint writer, the state
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


def _load_tool(module_name: str):
    """Import tools/<module_name>.py from beside this hook or the plugin root.

    Same resolution order as stop-redaction-gate's _load_gate. Returns None
    when no copy exists; the caller then degrades (exit 0 or an unfilled
    checkpoint), which is this hook's standing contract for anything it cannot
    measure (see module docstring: non-fatal by construction).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "tools")]
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidates.append(os.path.join(plugin_root, "tools"))
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(os.path.join(c, module_name + ".py")):
            sys.path.insert(0, c)
            return importlib.import_module(module_name)  # path must be set first
    _note(f"tools/{module_name}.py not found beside the hook; not measured",
          FileNotFoundError(candidates[0]))
    return None


def _load_scan():
    """The transcript scanner (context size, activity gate), or None."""
    return _load_tool("transcript_scan")


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


def _checkpoint_text(trigger: Trigger, transcript_path, facts_module) -> str:
    """The checkpoint markdown: measured transcript facts + git, no model."""
    session_id, cwd, ctx, model_id, level = trigger
    facts = (facts_module.summarize(transcript_path) if facts_module else
             {"user_requests": [], "files_touched": [], "commands": [], "errors": [],
              "last_assistant": "", "open_todos": []})
    session = {
        "level": level, "ctx": ctx, "model": model_id, "cwd": cwd,
        "session_id": session_id,
        "iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": (_git(cwd, "symbolic-ref", "--short", "HEAD")
                   or _git(cwd, "rev-parse", "--short", "HEAD")),
        "last_commit": _git(cwd, "log", "-1", "--oneline"),
        "git_status": _git(cwd, "status", "--porcelain"),
    }
    if facts_module is None:
        return (f"## Auto-checkpoint ({level}) — {session['iso']}\n\n"
                f"tools/checkpoint_summary.py not found; only git state measured.\n"
                f"- session_id: {session_id}\n- branch: {session['branch'] or '(unknown)'}\n"
                f"- last commit: {session['last_commit'] or '(none)'}\n"
                f"- git status:\n{session['git_status'] or '(clean)'}\n")
    return facts_module.render(facts, session)


def _write_checkpoint(trigger: Trigger, transcript_path) -> str:
    """Write the filled checkpoint (per-session + latest). Returns its path or ''."""
    root = os.path.join(os.path.expanduser("~"), ".claude", "memories", "checkpoints")
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        return ""
    text = _checkpoint_text(trigger, transcript_path, _load_tool("checkpoint_summary"))
    per_session = os.path.join(root, f"{trigger.session_id}.md")
    latest = os.path.join(root, "latest.md")
    try:
        with open(per_session, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(latest, "w", encoding="utf-8") as fh:
            fh.write(text)
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


def _notice(trigger: Trigger, path: str, warn: int, hard: int) -> dict:
    """Non-blocking Stop output: tell the user where the checkpoint is. The turn
    is never held and the model is never asked to delegate or write anything."""
    where = path or "n/a (checkpoint directory not writable)"
    model = trigger.model_id or "model"
    if trigger.level == "hard":
        message = (
            f"[context-guard] {trigger.ctx:,} tokens >= {hard:,} soft cap ({model}). "
            f"Checkpoint written by the hook: {where}. Run /clear, then resume "
            f"from that file (one targeted recall, no re-reading)."
        )
    else:
        message = (
            f"[context-guard] {trigger.ctx:,} tokens >= {warn:,} checkpoint threshold "
            f"({model}). Checkpoint written by the hook: {where}. "
            f"Nothing to do; hard stop at {hard:,}."
        )
    return {"systemMessage": message}


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

    path = _write_checkpoint(trigger, data.get("transcript_path"))
    _record_fire(trigger, data, since_offset, state)

    _exit(_notice(trigger, path, warn, hard))


if __name__ == "__main__":
    main()
