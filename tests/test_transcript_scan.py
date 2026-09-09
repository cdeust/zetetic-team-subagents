"""Unit tests for tools/transcript_scan.py — the bounded transcript reads.

Moved here with the mechanism itself when it was extracted from
hooks/stop-context-guard.py (that file had grown past the coding-standards §4
size limit, and the two scans were the coherent unit to lift). The assertions
are the ones that pinned the scans inside the hook: same cases, same expected
values, now addressed at the module that owns them. The hook keeps its own
thin wrappers and the tests that pin those.

Chunk-boundary and scan-cap tests monkeypatch CHUNK/MAX_BYTES down to a few
dozen bytes rather than writing multi-megabyte fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import transcript_scan as ts  # noqa: E402  (path must be set first)


def _jsonl(tmp_path, *records) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return str(path)


def _usage(ctx: int, model="claude-opus-5"):
    """A transcript record shaped like a real assistant usage line."""
    return {"message": {"model": model, "usage": {"input_tokens": ctx}}}


def _tool_use(name="Read"):
    """A transcript record carrying a tool_use content block."""
    return {"message": {"content": [{"type": "tool_use", "name": name}]}}


def _noted(sink):
    """Stand-in for the hook's _note, recording rather than printing."""
    def note(what, exc):
        sink.append((what, exc))
    return note


# ── usage_from_line ──────────────────────────────────────────────────────────

def test_usage_line_sums_all_three_input_token_fields():
    line = json.dumps({"message": {"model": "m", "usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 2}}})
    assert ts.usage_from_line(line) == (17, "m")


def test_usage_line_falls_back_to_a_top_level_model():
    line = json.dumps({"model": "top", "message": {"usage": {"input_tokens": 3}}})
    assert ts.usage_from_line(line) == (3, "top")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "not json",
        json.dumps({"message": {}}),                                  # no usage
        json.dumps({"message": {"usage": {}}}),                       # empty usage
        json.dumps({"message": {"usage": {"input_tokens": 0}}}),      # zero
        json.dumps({"message": {"usage": {"input_tokens": None}}}),   # null
        json.dumps({"type": "user", "content": "hi"}),                # not assistant
    ],
)
def test_usage_line_returns_none_for_a_non_usage_line(line):
    assert ts.usage_from_line(line) is None


# ── read_last_usage: the bounded reverse-tail read ───────────────────────────

def test_read_last_usage_finds_the_most_recent_record(tmp_path):
    path = _jsonl(tmp_path, _usage(100), {"type": "user"}, _usage(999))
    assert ts.read_last_usage(path) == (999, "claude-opus-5")


def test_read_last_usage_skips_trailing_non_usage_lines(tmp_path):
    path = _jsonl(tmp_path, _usage(42), {"type": "user"}, {"type": "user"})
    assert ts.read_last_usage(path) == (42, "claude-opus-5")


@pytest.mark.parametrize("path", [None, "", 42, [], "/nonexistent/transcript.jsonl"])
def test_read_last_usage_is_none_for_an_unusable_path(path):
    assert ts.read_last_usage(path) == (None, None)


def test_read_last_usage_is_none_for_an_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert ts.read_last_usage(str(path)) == (None, None)


def test_read_last_usage_is_none_when_no_line_carries_usage(tmp_path):
    path = _jsonl(tmp_path, {"type": "user"}, {"type": "user"})
    assert ts.read_last_usage(path) == (None, None)


def test_read_last_usage_steps_back_across_chunk_boundaries(tmp_path, monkeypatch):
    """The record can sit further back than one chunk; the loop must step."""
    monkeypatch.setattr(ts, "CHUNK", 64)
    padding = [{"type": "user", "pad": "x" * 100} for _ in range(20)]
    path = _jsonl(tmp_path, _usage(777), *padding)
    assert ts.read_last_usage(path) == (777, "claude-opus-5")


def test_read_last_usage_reassembles_a_line_split_by_a_chunk_boundary(
    tmp_path, monkeypatch
):
    """A usage line longer than one chunk must still parse, via the carry."""
    monkeypatch.setattr(ts, "CHUNK", 32)
    record = {"message": {"model": "m", "usage": {"input_tokens": 5}},
              "pad": "y" * 500}
    path = _jsonl(tmp_path, record)
    assert ts.read_last_usage(path) == (5, "m")


def test_read_last_usage_stops_at_the_scan_cap(tmp_path, monkeypatch):
    """The hard safety bound: a record beyond the cap is not found, and the
    read still terminates rather than walking a 1 GB file."""
    monkeypatch.setattr(ts, "CHUNK", 64)
    monkeypatch.setattr(ts, "MAX_BYTES", 128)
    padding = [{"type": "user", "pad": "z" * 200} for _ in range(10)]
    path = _jsonl(tmp_path, _usage(1234), *padding)
    assert ts.read_last_usage(path) == (None, None)


def test_read_last_usage_tolerates_invalid_utf8(tmp_path):
    """A chunk boundary can split a multi-byte sequence; it must not raise."""
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"\xff\xfe garbage\n" + json.dumps(_usage(11)).encode() + b"\n")
    assert ts.read_last_usage(str(path)) == (11, "claude-opus-5")


# ── line_has_tool_use ────────────────────────────────────────────────────────

def test_line_has_tool_use():
    assert ts.line_has_tool_use(json.dumps(_tool_use())) is True
    assert ts.line_has_tool_use(json.dumps(_usage(1))) is False
    assert ts.line_has_tool_use("not json") is False
    assert ts.line_has_tool_use("") is False


# ── has_activity_since: the bounded forward scan ─────────────────────────────

def test_has_activity_since_finds_a_tool_use(tmp_path):
    path = _jsonl(tmp_path, _usage(10), _tool_use())
    assert ts.has_activity_since(path, 0, _noted([])) is True


def test_has_activity_since_is_false_for_usage_only_transcript(tmp_path):
    path = _jsonl(tmp_path, _usage(10), _usage(20))
    assert ts.has_activity_since(path, 0, _noted([])) is False


def test_has_activity_since_ignores_activity_before_the_offset(tmp_path):
    path = _jsonl(tmp_path, _tool_use(), _usage(10))
    assert ts.has_activity_since(path, Path(path).stat().st_size, _noted([])) is False


def test_has_activity_since_rescans_when_the_offset_is_stale(tmp_path):
    """An offset past EOF means the transcript was rotated or replaced; a
    stale baseline must not be read as "caught up"."""
    path = _jsonl(tmp_path, _tool_use())
    assert ts.has_activity_since(path, 10_000_000, _noted([])) is True


def test_has_activity_since_fails_open_on_a_missing_file(tmp_path):
    notes = []
    assert ts.has_activity_since(str(tmp_path / "gone.jsonl"), 0, _noted(notes)) is True
    assert notes, "a non-fatal failure must be reported, not swallowed"


def test_has_activity_since_fails_open_at_the_scan_cap(tmp_path, monkeypatch):
    """Cap hit before EOF: we could not verify the skip is safe, so fire."""
    monkeypatch.setattr(ts, "CHUNK", 64)
    monkeypatch.setattr(ts, "MAX_BYTES", 128)
    padding = [{"type": "user", "pad": "z" * 200} for _ in range(10)]
    path = _jsonl(tmp_path, *padding)
    assert ts.has_activity_since(path, 0, _noted([])) is True


def test_has_activity_since_finds_a_tool_use_split_across_chunks(tmp_path, monkeypatch):
    """The carry must reassemble a tool_use line straddling a chunk boundary."""
    monkeypatch.setattr(ts, "CHUNK", 32)
    record = dict(_tool_use(), pad="w" * 500)
    path = _jsonl(tmp_path, record)
    assert ts.has_activity_since(path, 0, _noted([])) is True
