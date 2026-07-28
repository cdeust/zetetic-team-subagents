"""Unit tests for hooks/stop-context-guard.py's payload and threshold helpers.

These two functions were extracted from `main()` so that the locals they feed
are bound on every path (CodeQL py/uninitialized-local-variable, alerts #28/#29
— the annotation-based fix did not satisfy the query because it is
intraprocedural and does not read `NoReturn`). Extracting them for an analyser's
benefit only pays off if the extracted contract is actually pinned, so it is
pinned here: every branch of both helpers, including the ones that exist to keep
the hook fail-open.

The module is loaded by path rather than imported: `stop-context-guard.py` has
hyphens in its name and hooks/ is not a package, so there is no dotted path for
it. That also keeps the hook's own `sys.exit()`-based flow out of these tests —
the helpers are pure and return.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "stop-context-guard.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("stop_context_guard", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_hook()


# ── _read_payload ────────────────────────────────────────────────────────────

def test_read_payload_returns_the_parsed_object(monkeypatch):
    payload = {"session_id": "s1", "cwd": "/tmp/x"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert guard._read_payload() == payload


@pytest.mark.parametrize(
    "raw",
    [
        "",                 # empty stdin — hook invoked with no payload
        "not json at all",  # plain text
        '{"unclosed": ',    # truncated object
        "\x00\x01",         # binary noise
    ],
)
def test_read_payload_returns_none_on_unparseable_stdin(monkeypatch, raw):
    """The fail-open contract: a broken payload must not raise out of the hook."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    assert guard._read_payload() is None


@pytest.mark.parametrize("raw", ["42", '"a string"', "[1, 2]", "null", "true"])
def test_read_payload_passes_through_valid_non_objects(monkeypatch, raw):
    """Valid JSON that is not an object parses fine; main() rejects it by shape.

    Pinned separately from the None case because the two reach the same exit via
    DIFFERENT routes, and collapsing them in a test would hide a regression that
    made one of them raise instead.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    result = guard._read_payload()
    assert not isinstance(result, dict)


@pytest.mark.parametrize("raw", ["{}", "", "garbage", "[]", "null", "\x00"])
def test_read_payload_never_raises(monkeypatch, raw):
    """The property the extraction exists for: the call always RETURNS.

    `main()` reads `data` unconditionally on the line after the call, so the
    only way that read can be unbound is if this function propagates instead of
    returning. Totality is the contract; the value itself is checked above.
    """
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    guard._read_payload()  # must not raise


# ── _level_for ───────────────────────────────────────────────────────────────

WARN, HARD = 100, 200


@pytest.mark.parametrize(
    "ctx,expected",
    [
        (0, None),          # far below
        (99, None),         # just below warn
        (100, "warn"),      # exactly warn — inclusive
        (150, "warn"),      # between
        (199, "warn"),      # just below hard
        (200, "hard"),      # exactly hard — inclusive
        (10_000, "hard"),   # far above
    ],
)
def test_level_for_boundaries(ctx, expected):
    assert guard._level_for(ctx, WARN, HARD) is expected


def test_level_for_returns_on_every_branch():
    """Total by construction — the reason `level` is bound in main()."""
    for ctx in range(0, 260, 7):
        assert guard._level_for(ctx, WARN, HARD) in {None, "warn", "hard"}


def test_level_for_prefers_hard_when_thresholds_coincide():
    """Degenerate config (warn == hard) must resolve to the stricter band.

    `_thresholds` rejects warn >= hard and falls back to defaults, so this is
    not reachable through the hook today — but the helper is public to the
    module and the ordering is the part a future edit could silently invert.
    """
    assert guard._level_for(150, 150, 150) == "hard"


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour: thresholds, the bounded reverse-tail read, the checkpoint stub,
# level state, and main()'s decision ladder.
#
# The two helpers above were extracted for an analyser; everything below is the
# hook's actual job. Coverage of this module was 20% (issue #71) because the
# only other exercise it got was a subprocess run, whose in-process statements
# coverage.py cannot see. Every test here drives the module in-process, in an
# isolated HOME and STATE_DIR, so no test can read or write the real
# ~/.claude/memories/checkpoints (rules/coding-standards.md §13.1 G3).
# ─────────────────────────────────────────────────────────────────────────────

import os
import subprocess


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def isolate_guard(tmp_path, monkeypatch):
    """Redirect HOME, STATE_DIR and the threshold config into a tmp tree.

    `_write_stub` writes into `~/.claude/memories/checkpoints` and `_save_level`
    into STATE_DIR (default /tmp), both keyed by session id. Left alone, a test
    run would overwrite the developer's real checkpoint file and could observe a
    previous run's level state.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(guard, "STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(
        guard, "CONFIG_PATH", str(home / ".claude" / "ctxguard-thresholds.json")
    )
    return tmp_path


def _jsonl(tmp_path, *records) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return str(path)


def _usage(ctx: int, model="claude-opus-5"):
    """A transcript record shaped like a real assistant usage line."""
    return {"message": {"model": model, "usage": {"input_tokens": ctx}}}


def _run_main(monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as excinfo:
        guard.main()
    return excinfo.value.code


# ── _exit ────────────────────────────────────────────────────────────────────

def test_exit_without_a_payload_is_silent(capsys):
    with pytest.raises(SystemExit) as excinfo:
        guard._exit()
    assert excinfo.value.code == 0
    assert capsys.readouterr().out == ""


def test_exit_with_a_payload_writes_json(capsys):
    with pytest.raises(SystemExit):
        guard._exit({"decision": "block"})
    assert json.loads(capsys.readouterr().out) == {"decision": "block"}


def test_note_names_the_tool_and_the_exception(capsys):
    guard._note("config unreadable", ValueError("bad"))
    err = capsys.readouterr().err
    assert "[ctxguard]" in err and "ValueError" in err and "bad" in err


# ── _thresholds ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-opus-5", (180_000, 200_000)),
        ("claude-sonnet-5", (180_000, 200_000)),
        ("claude-haiku-4-5-20251001", (120_000, 170_000)),
        ("claude-fable-5", (120_000, 160_000)),
        ("mythos-1", (120_000, 160_000)),
    ],
)
def test_thresholds_per_model_family(model, expected):
    assert guard._thresholds(model) == expected


@pytest.mark.parametrize("model", [None, "", "some-unknown-model"])
def test_thresholds_fall_back_to_the_default_band(model):
    assert guard._thresholds(model) == (180_000, 200_000)


def test_thresholds_read_an_operator_config(isolate_guard):
    Path(guard.CONFIG_PATH).write_text(json.dumps({
        "models": [{"match": "opus", "warn": 1000, "hard": 2000}],
        "default": {"warn": 10, "hard": 20},
    }))
    assert guard._thresholds("claude-opus-5") == (1000, 2000)


def test_thresholds_use_the_configs_default_for_an_unmatched_model(isolate_guard):
    Path(guard.CONFIG_PATH).write_text(json.dumps({
        "models": [{"match": "opus", "warn": 1000, "hard": 2000}],
        "default": {"warn": 30, "hard": 40},
    }))
    assert guard._thresholds("other") == (30, 40)


def test_thresholds_report_and_recover_from_an_unreadable_config(
    isolate_guard, capsys
):
    """Degraded, not silent: the note is the signal that config was ignored."""
    Path(guard.CONFIG_PATH).write_text("{not json")
    assert guard._thresholds("claude-opus-5") == (180_000, 200_000)
    assert "unreadable" in capsys.readouterr().err


def test_thresholds_ignore_a_config_of_the_wrong_shape(isolate_guard):
    Path(guard.CONFIG_PATH).write_text(json.dumps({"models": "not-a-list"}))
    assert guard._thresholds("claude-opus-5") == (180_000, 200_000)


def test_thresholds_skip_a_malformed_entry_and_keep_matching(isolate_guard):
    Path(guard.CONFIG_PATH).write_text(json.dumps({
        "models": [{"no_match_key": 1}, {"match": "opus", "warn": 5, "hard": 9}],
        "default": {"warn": 1, "hard": 2},
    }))
    assert guard._thresholds("claude-opus-5") == (5, 9)


@pytest.mark.parametrize(
    "entry",
    [
        {"match": "opus", "warn": 500},                 # missing hard
        {"match": "opus", "warn": 900, "hard": 100},    # inverted
        {"match": "opus", "warn": 0, "hard": 100},      # non-positive
        {"match": "opus", "warn": "x", "hard": "y"},    # non-numeric
        {"match": "opus", "warn": 100, "hard": 100},    # equal, so not warn < hard
    ],
)
def test_thresholds_reject_an_entry_that_breaks_the_postcondition(
    isolate_guard, entry
):
    """Postcondition is 0 < warn < hard; anything else falls back."""
    Path(guard.CONFIG_PATH).write_text(json.dumps({"models": [entry]}))
    assert guard._thresholds("claude-opus-5") == (180_000, 200_000)


# ── _usage_from_line ─────────────────────────────────────────────────────────

def test_usage_line_sums_all_three_input_token_fields():
    line = json.dumps({"message": {"model": "m", "usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 2}}})
    assert guard._usage_from_line(line) == (17, "m")


def test_usage_line_falls_back_to_a_top_level_model():
    line = json.dumps({"model": "top", "message": {"usage": {"input_tokens": 3}}})
    assert guard._usage_from_line(line) == (3, "top")


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
    assert guard._usage_from_line(line) is None


# ── _read_last_usage: the bounded reverse-tail read ──────────────────────────

def test_read_last_usage_finds_the_most_recent_record(isolate_guard):
    path = _jsonl(isolate_guard, _usage(100), {"type": "user"}, _usage(999))
    assert guard._read_last_usage(path) == (999, "claude-opus-5")


def test_read_last_usage_skips_trailing_non_usage_lines(isolate_guard):
    path = _jsonl(isolate_guard, _usage(42), {"type": "user"}, {"type": "user"})
    assert guard._read_last_usage(path) == (42, "claude-opus-5")


@pytest.mark.parametrize("path", [None, "", 42, [], "/nonexistent/transcript.jsonl"])
def test_read_last_usage_is_none_for_an_unusable_path(path):
    assert guard._read_last_usage(path) == (None, None)


def test_read_last_usage_is_none_for_an_empty_file(isolate_guard):
    path = isolate_guard / "empty.jsonl"
    path.write_text("")
    assert guard._read_last_usage(str(path)) == (None, None)


def test_read_last_usage_is_none_when_no_line_carries_usage(isolate_guard):
    path = _jsonl(isolate_guard, {"type": "user"}, {"type": "user"})
    assert guard._read_last_usage(path) == (None, None)


def test_read_last_usage_steps_back_across_chunk_boundaries(
    isolate_guard, monkeypatch
):
    """The record can sit further back than one chunk; the loop must step."""
    monkeypatch.setattr(guard, "TAIL_CHUNK", 64)
    padding = [{"type": "user", "pad": "x" * 100} for _ in range(20)]
    path = _jsonl(isolate_guard, _usage(777), *padding)
    assert guard._read_last_usage(path) == (777, "claude-opus-5")


def test_read_last_usage_reassembles_a_line_split_by_a_chunk_boundary(
    isolate_guard, monkeypatch
):
    """A usage line longer than one chunk must still parse, via the carry."""
    monkeypatch.setattr(guard, "TAIL_CHUNK", 32)
    record = {"message": {"model": "m", "usage": {"input_tokens": 5}},
              "pad": "y" * 500}
    path = _jsonl(isolate_guard, record)
    assert guard._read_last_usage(path) == (5, "m")


def test_read_last_usage_stops_at_the_scan_cap(isolate_guard, monkeypatch):
    """The hard safety bound: a record beyond the cap is not found, and the
    read still terminates rather than walking a 1 GB file."""
    monkeypatch.setattr(guard, "TAIL_CHUNK", 64)
    monkeypatch.setattr(guard, "TAIL_MAX_BYTES", 128)
    padding = [{"type": "user", "pad": "z" * 200} for _ in range(10)]
    path = _jsonl(isolate_guard, _usage(1234), *padding)
    assert guard._read_last_usage(path) == (None, None)


def test_read_last_usage_tolerates_invalid_utf8(isolate_guard):
    """A chunk boundary can split a multi-byte sequence; it must not raise."""
    path = isolate_guard / "t.jsonl"
    path.write_bytes(b"\xff\xfe garbage\n" + json.dumps(_usage(11)).encode() + b"\n")
    assert guard._read_last_usage(str(path)) == (11, "claude-opus-5")


# ── _git and the checkpoint stub ─────────────────────────────────────────────

def test_git_returns_stripped_stdout(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=" main \n"))
    assert guard._git("/repo", "symbolic-ref") == "main"


def test_git_returns_empty_on_any_failure(monkeypatch):
    def _raise(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert guard._git("/repo", "status") == ""


def test_write_stub_creates_per_session_and_latest(isolate_guard, monkeypatch):
    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    path = guard._write_stub("sess123", "/work", 150_000, "claude-opus-5", "warn")
    assert path.endswith("sess123.md")
    body = Path(path).read_text()
    latest = Path(path).parent / "latest.md"
    assert latest.read_text() == body


def test_stub_records_the_session_facts(isolate_guard, monkeypatch):
    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    path = guard._write_stub("sess123", "/work", 150_000, "claude-opus-5", "warn")
    body = Path(path).read_text()
    assert "150,000" in body
    assert "claude-opus-5" in body
    assert "/work" in body
    assert "sess123" in body


def test_stub_carries_the_letta_schema_sections(isolate_guard, monkeypatch):
    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    body = Path(
        guard._write_stub("s", "/w", 1, "m", "warn")
    ).read_text()
    for section in ("### Goals", "### File references", "### Errors and fixes",
                    "### Current state", "### Next steps", "### Resume contract"):
        assert section in body


def test_stub_seeds_file_references_from_git_status(isolate_guard, monkeypatch):
    monkeypatch.setattr(
        guard, "_git",
        lambda cwd, *a: " M tools/x.sh" if a[0] == "status" else "branchy",
    )
    body = Path(guard._write_stub("s", "/w", 1, "m", "hard")).read_text()
    assert "- M tools/x.sh" in body
    assert "branchy" in body


def test_stub_says_so_when_the_tree_is_clean(isolate_guard, monkeypatch):
    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    body = Path(guard._write_stub("s", "/w", 1, "m", "warn")).read_text()
    assert "(working tree clean)" in body


def test_write_stub_returns_empty_when_the_directory_cannot_be_made(
    isolate_guard, monkeypatch
):
    """Fail-open: an unwritable HOME must not break the hook."""

    def _raise(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(os, "makedirs", _raise)
    assert guard._write_stub("s", "/w", 1, "m", "warn") == ""


def test_write_stub_returns_empty_when_the_file_cannot_be_written(
    isolate_guard, monkeypatch
):
    import builtins

    real_open = builtins.open

    def _open(path, *a, **k):
        if str(path).endswith(".md"):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    monkeypatch.setattr(builtins, "open", _open)
    assert guard._write_stub("s", "/w", 1, "m", "warn") == ""


# ── level state ──────────────────────────────────────────────────────────────

def test_level_state_defaults_to_none(isolate_guard):
    assert guard._load_level("fresh") == "none"


def test_level_state_round_trips(isolate_guard):
    guard._save_level("s1", "warn")
    assert guard._load_level("s1") == "warn"


def test_level_state_is_per_session(isolate_guard):
    guard._save_level("s1", "hard")
    assert guard._load_level("s2") == "none"


def test_level_state_defaults_to_none_on_a_corrupt_file(isolate_guard):
    path = Path(guard.STATE_DIR) / "zetetic-ctxguard-s1.json"
    path.write_text("{not json")
    assert guard._load_level("s1") == "none"


def test_save_level_reports_but_survives_an_unwritable_state_dir(
    isolate_guard, monkeypatch, capsys
):
    monkeypatch.setattr(guard, "STATE_DIR", str(isolate_guard / "missing"))
    guard._save_level("s1", "warn")  # must not raise
    assert "level-state write failed" in capsys.readouterr().err


# ── reason strings ───────────────────────────────────────────────────────────

def test_warn_reason_is_actionable(isolate_guard):
    reason = guard._warn_reason(185_000, "/stub.md", 180_000, 200_000)
    assert "185,000" in reason and "180,000" in reason and "200,000" in reason
    assert "memory-writer" in reason
    assert "/stub.md" in reason
    assert "NOT the end of the session" in reason


def test_warn_reason_handles_a_missing_stub_path():
    assert "n/a" in guard._warn_reason(1, "", 1, 2)


def test_block_reason_states_the_cap_and_the_exit_protocol():
    reason = guard._block_reason(205_000, "/stub.md", 200_000)
    assert "205,000" in reason and "200,000" in reason
    assert "CHECKPOINT — context cleared." in reason
    assert "Do NOT start new substantive work" in reason


def test_block_reason_handles_a_missing_stub_path():
    assert "n/a" in guard._block_reason(1, "", 1)


# ── main: the decision ladder ────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["not json", "[]", "42", "null", '"s"'])
def test_main_exits_silently_on_an_unusable_payload(monkeypatch, raw, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    with pytest.raises(SystemExit) as excinfo:
        guard.main()
    assert excinfo.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_exits_during_a_forced_continuation(monkeypatch, isolate_guard, capsys):
    payload = {"stop_hook_active": True,
               "transcript_path": _jsonl(isolate_guard, _usage(999_999))}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == "", "the loop guard must not emit a decision"


def test_main_exits_when_no_usage_can_be_read(monkeypatch, isolate_guard, capsys):
    payload = {"session_id": "s", "transcript_path": str(isolate_guard / "nope")}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_main_is_silent_below_the_warn_threshold(monkeypatch, isolate_guard, capsys):
    payload = {"session_id": "s",
               "transcript_path": _jsonl(isolate_guard, _usage(1000))}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_main_emits_the_warn_decision_on_crossing_up(
    monkeypatch, isolate_guard, capsys
):
    payload = {"session_id": "s", "cwd": str(isolate_guard),
               "transcript_path": _jsonl(isolate_guard, _usage(185_000))}
    assert _run_main(monkeypatch, payload) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "CHECKPOINT THRESHOLD" in decision["reason"]
    assert "checkpoint threshold" in decision["systemMessage"]
    assert guard._load_level("s") == "warn"


def test_main_emits_the_hard_decision_above_the_cap(
    monkeypatch, isolate_guard, capsys
):
    payload = {"session_id": "s", "cwd": str(isolate_guard),
               "transcript_path": _jsonl(isolate_guard, _usage(250_000))}
    _run_main(monkeypatch, payload)
    decision = json.loads(capsys.readouterr().out)
    assert "SOFT CAP REACHED" in decision["reason"]
    assert "soft cap" in decision["systemMessage"]
    assert guard._load_level("s") == "hard"


def test_main_fires_each_level_only_once(monkeypatch, isolate_guard, capsys):
    """Crossing UP is the trigger; staying in the band must stay quiet."""
    payload = {"session_id": "s", "cwd": str(isolate_guard),
               "transcript_path": _jsonl(isolate_guard, _usage(185_000))}
    _run_main(monkeypatch, payload)
    capsys.readouterr()
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_main_still_escalates_from_warn_to_hard(monkeypatch, isolate_guard, capsys):
    """One-time-per-level, not one-time-per-session: hard must still fire."""
    warn_payload = {"session_id": "s", "cwd": str(isolate_guard),
                    "transcript_path": _jsonl(isolate_guard, _usage(185_000))}
    _run_main(monkeypatch, warn_payload)
    capsys.readouterr()
    hard_path = isolate_guard / "t2.jsonl"
    hard_path.write_text(json.dumps(_usage(250_000)) + "\n")
    _run_main(monkeypatch, {"session_id": "s", "cwd": str(isolate_guard),
                            "transcript_path": str(hard_path)})
    assert "SOFT CAP REACHED" in json.loads(capsys.readouterr().out)["reason"]


def test_main_does_not_downgrade_from_hard_to_warn(monkeypatch, isolate_guard, capsys):
    guard._save_level("s", "hard")
    payload = {"session_id": "s", "cwd": str(isolate_guard),
               "transcript_path": _jsonl(isolate_guard, _usage(185_000))}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_main_uses_the_model_specific_band(monkeypatch, isolate_guard, capsys):
    """125k is under opus's warn band but over haiku's, so the model decides."""
    payload = {"session_id": "s", "cwd": str(isolate_guard),
               "transcript_path": _jsonl(
                   isolate_guard, _usage(125_000, "claude-haiku-4-5-20251001"))}
    _run_main(monkeypatch, payload)
    assert "CHECKPOINT THRESHOLD" in json.loads(capsys.readouterr().out)["reason"]

    guard._save_level("s2", "none")
    payload2 = {"session_id": "s2", "cwd": str(isolate_guard),
                "transcript_path": _jsonl(
                    isolate_guard, _usage(125_000, "claude-opus-5"))}
    assert _run_main(monkeypatch, payload2) == 0
    assert capsys.readouterr().out == ""


def test_main_defaults_cwd_when_the_payload_omits_it(
    monkeypatch, isolate_guard, capsys
):
    monkeypatch.setattr(guard, "_git", lambda cwd, *a: "")
    payload = {"session_id": "s",
               "transcript_path": _jsonl(isolate_guard, _usage(250_000))}
    _run_main(monkeypatch, payload)
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
