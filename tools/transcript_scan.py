#!/usr/bin/env python3
"""transcript_scan.py — bounded reads over a Claude Code JSONL transcript.

Extracted from ``hooks/stop-context-guard.py`` (which had grown past the
coding-standards §4 file-size limit) so the two scans live where the repo
already keeps hook-shared mechanism: beside ``redaction_gate.py``, loaded by
the same resolve-beside-the-hook pattern. Nothing here does policy — it
answers two questions and holds no state:

  - ``read_last_usage``: what was the context size at the most recent
    assistant turn? (backward scan; the record is near the end)
  - ``has_activity_since``: has anything checkpointable happened since byte
    N? (forward scan from that offset)

Both are BOUNDED: peak memory is O(CHUNK), and each caps total bytes scanned
at MAX_BYTES so an unbounded transcript cannot stall a Stop hook. Both
decode UTF-8 with errors='replace', so a chunk boundary splitting a
multi-byte sequence can never raise.
"""
from __future__ import annotations

import json
import os

# --- Bounded reverse-tail read parameters ------------------------------------
# Claude Code transcripts grow to 100MB–1GB in long sessions, and the Stop
# hook that calls this runs on every turn. Reading the whole file (readlines)
# is O(file size) in memory; we instead seek to the tail and scan backward.
#
# CHUNK = 64 KiB (a power-of-two block multiple). Justification, measured
# on a real 24.5MB transcript at
#   ~/.claude/projects/-Users-cdeust-Developments-Cortex/<uuid>.jsonl :
#   - the last assistant `usage` record was 7,591 bytes from EOF;
#   - usage JSONL lines were min=1,016 / median=1,729 / max=32,769 bytes.
# A single 64 KiB tail read covers the last-usage offset ~8.6x over and the
# largest single usage line ~2x over, so one chunk suffices in practice.
# The usage record is rewritten on every assistant turn, so it is always near
# the end. Chunk-stepping with MAX_BYTES is a hard safety bound, not a
# tuning knob.
CHUNK = 64 * 1024          # 65536 bytes
MAX_BYTES = 4 * 1024 * 1024  # cap total bytes scanned at 4 MiB


def usage_from_line(line: str):
    """Parse one JSONL line; return (ctx, model) if it carries a positive
    assistant usage record, else None. Pure, no I/O.

    Context tokens are summed exactly as Claude Code's `used_percentage`:
    input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
    """
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


def line_has_tool_use(line: str) -> bool:
    """True if a JSONL transcript line's assistant message content carries
    a tool_use block. Pure, no I/O."""
    line = line.strip()
    if not line:
        return False
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    content = (obj.get("message") or {}).get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in content
    )


def _split_complete_lines(buf: str, at_file_start: bool):
    """Split a backward-scan window into (carry, complete_lines).

    Unless the window reaches byte 0, its first segment is a partial line
    whose true beginning lies in an earlier chunk; it is held back as carry
    and only the complete lines after it are scanned. Returns (carry, None)
    when the window holds no newline at all — the caller keeps accumulating.
    """
    if at_file_start:
        return "", buf.split("\n")
    nl = buf.find("\n")
    if nl == -1:
        return buf, None
    return buf[:nl], buf[nl + 1:].split("\n")


def _scan_backward(fh, size: int):
    """Walk the tail backward in CHUNK blocks, returning the first usage
    record found (newest first), or None within the MAX_BYTES cap."""
    carry = ""   # bytes of a line split across the chunk boundary
    pos = size   # exclusive high-water mark of bytes not yet read
    scanned = 0
    while pos > 0 and scanned < MAX_BYTES:
        read_size = min(CHUNK, pos)
        pos -= read_size
        scanned += read_size
        fh.seek(pos)
        chunk = fh.read(read_size).decode("utf-8", errors="replace")
        carry, lines = _split_complete_lines(chunk + carry, at_file_start=pos == 0)
        if lines is None:
            continue
        for line in reversed(lines):
            hit = usage_from_line(line)
            if hit is not None:
                return hit
    # Cap reached or whole file consumed; check any final carried line.
    return usage_from_line(carry) if carry else None


def read_last_usage(transcript_path):
    """Return (context_tokens, model_id) from the most recent assistant usage,
    or (None, None) if unavailable.

    Precondition:  transcript_path is a path string (or None).
    Postcondition: returns (ctx, model) for the last line carrying a positive
                   usage record within the scanned tail, else (None, None).
                   On any missing/unreadable file or non-str path, returns
                   (None, None) — identical to the previous readlines() contract.
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
        return _scan_backward(fh, size) or (None, None)
    except OSError:
        return None, None
    finally:
        fh.close()


def _scan_forward_for_tool_use(fh, start: int, size: int) -> bool:
    """Walk forward from `start` in CHUNK blocks, early-exiting on the first
    tool_use. Fail-open: True when the MAX_BYTES cap is hit before EOF."""
    pos = start
    scanned = 0
    carry = ""
    while pos < size and scanned < MAX_BYTES:
        fh.seek(pos)
        chunk_bytes = fh.read(min(CHUNK, size - pos))
        if not chunk_bytes:
            break
        pos += len(chunk_bytes)
        scanned += len(chunk_bytes)
        lines = (carry + chunk_bytes.decode("utf-8", errors="replace")).split("\n")
        carry = lines[-1]  # last (possibly partial) line held for next chunk
        if any(line_has_tool_use(line) for line in lines[:-1]):
            return True
    if carry and line_has_tool_use(carry):
        return True
    return pos < size  # False only after a clean scan to EOF; cap hit -> fail-open


def has_activity_since(transcript_path, since_offset: int, note) -> bool:
    """True if the transcript contains at least one tool_use content block
    at or after byte `since_offset`.

    Fail-open: if the scan cap is hit without finding one, return True
    (preserve the previous always-fire behavior rather than risk silently
    dropping a checkpoint we could not fully verify is safe to skip).
    since_offset larger than the current file size means the offset is stale
    (the transcript was replaced/rotated between fires) and cannot be trusted
    as "caught up" -- rescan from 0 instead of concluding there is nothing new.

    `note` is the caller's one-line stderr reporter for a non-fatal failure,
    so this module degrades open without owning the hook's logging.

    Precondition:  transcript_path is a path string (or None); since_offset
                   is a non-negative int (0 scans the whole file).
    Postcondition: True if a tool_use block was found or the file could not
                   be read/parsed at all (fail-open); False only after a
                   clean scan to EOF within the byte cap found none.
    """
    try:
        size = os.stat(transcript_path).st_size
    except (OSError, TypeError, ValueError) as exc:
        note("ctxguard activity scan: transcript unreadable", exc)
        return True  # can't tell -> don't silently skip

    since_offset = max(0, since_offset or 0)
    if since_offset > size:
        since_offset = 0  # stale baseline -> rescan whole file
    elif since_offset == size:
        return False  # nothing appended since last fire / session start

    try:
        fh = open(transcript_path, "rb")
    except (OSError, TypeError, ValueError) as exc:
        note("ctxguard activity scan: transcript unopenable", exc)
        return True

    try:
        return _scan_forward_for_tool_use(fh, since_offset, size)
    except OSError as exc:
        note("ctxguard activity scan failed mid-read", exc)
        return True
    finally:
        fh.close()
