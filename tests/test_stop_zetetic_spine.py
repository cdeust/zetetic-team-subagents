"""Unit tests for hooks/stop-zetetic-spine.py's tool-shape patterns.

EVIDENCE_RE decides whether the session showed spine evidence (a recall/search
beat) before a claim-producing edit. It matches MCP tool names literally, and an
MCP tool's name is derived by the host as
`mcp__plugin_<plugin-name>_<mcp-server-key>__<tool>` — so a plugin RENAME
silently invalidates every literal here: the pattern stops matching, the hook
sees no evidence, and it blocks (or, symmetrically, a stale literal that can
never appear makes that arm dead). Cortex renamed its plugin `cortex` ->
`hypermnesia-mcp` in 4.15.0, which is exactly this failure. The literals are
pinned here so the next rename fails a test instead of degrading a guard.

The module is loaded by path rather than imported, for the same reason as
test_context_guard.py: hyphenated filename, hooks/ is not a package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "stop-zetetic-spine.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("stop_zetetic_spine", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


spine = _load_hook()


def _tool_use(name: str) -> str:
    """A transcript fragment as the hook sees it — a JSON tool_use record."""
    return '{"type": "tool_use", "name": "%s", "input": {}}' % name


# ── EVIDENCE_RE — the memory/web beats that count as spine evidence ───────────

CURRENT_MEMORY_TOOLS = [
    "mcp__plugin_hypermnesia-mcp_cortex__recall",
    "mcp__plugin_hypermnesia-mcp_cortex__unified_search",
    "mcp__plugin_hypermnesia-mcp_cortex__navigate_memory",
]


@pytest.mark.parametrize("tool", CURRENT_MEMORY_TOOLS)
def test_evidence_re_matches_current_memory_tool_names(tool):
    assert spine.EVIDENCE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", ["WebSearch", "WebFetch"])
def test_evidence_re_matches_web_evidence_tools(tool):
    assert spine.EVIDENCE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", CURRENT_MEMORY_TOOLS)
def test_evidence_re_rejects_pre_rename_cortex_prefix(tool):
    """The 4.14.x prefix must not linger: it can never appear in a transcript.

    A pattern that still accepted it would keep a dead arm alive and hide the
    fact that the live literals were never updated.
    """
    stale = tool.replace("mcp__plugin_hypermnesia-mcp_cortex__",
                         "mcp__plugin_cortex_cortex__")
    assert not spine.EVIDENCE_RE.search(_tool_use(stale))


def test_evidence_re_ignores_an_unrelated_tool():
    assert not spine.EVIDENCE_RE.search(_tool_use("Read"))


def test_evidence_re_tolerates_json_whitespace():
    fragment = '{"name"  :   "mcp__plugin_hypermnesia-mcp_cortex__recall"}'
    assert spine.EVIDENCE_RE.search(fragment)


def test_remember_is_not_evidence():
    """A write is not a recall — remember must not satisfy the spine."""
    assert not spine.EVIDENCE_RE.search(
        _tool_use("mcp__plugin_hypermnesia-mcp_cortex__remember"))


# ── CHANGE_RE — the claim/state-producing calls the spine guards ──────────────

@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_change_re_matches_state_producing_tools(tool):
    assert spine.CHANGE_RE.search(_tool_use(tool))


@pytest.mark.parametrize("tool", ["Read", "Grep", "WebSearch"])
def test_change_re_ignores_read_only_tools(tool):
    assert not spine.CHANGE_RE.search(_tool_use(tool))


# ── MEMORY_CMD_RE — the shell-side memory beat ────────────────────────────────

@pytest.mark.parametrize("cmd", ["memory-tool.sh view", "memory-tool.sh  search"])
def test_memory_cmd_re_matches_read_subcommands(cmd):
    assert spine.MEMORY_CMD_RE.search(cmd)


def test_memory_cmd_re_ignores_write_subcommand():
    assert not spine.MEMORY_CMD_RE.search("memory-tool.sh append 'note'")


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour: the two tiers, the transcript read, and the fail-open routes.
#
# The regex tests above pin WHAT counts as evidence. The tests below pin what
# the hook DOES with that answer, which is where the product-safety rule lives:
# the default tier is report-only and one-time per session, and only an explicit
# marker or env opt-in may block a turn. Coverage of this module was 30% before
# these (issue #71) with every decision path unexercised.
# ─────────────────────────────────────────────────────────────────────────────

import io
import json
import os
import subprocess
import sys


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_REAL_REPO_ROOT = spine.repo_root

EDIT = _tool_use("Edit")
RECALL = _tool_use("mcp__plugin_hypermnesia-mcp_cortex__recall")


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Per-test STATE_DIR and repo root.

    STATE_DIR defaults to /tmp and the warn-state file is keyed by session id, so
    without this two runs of the suite on one machine would see each other's
    marker and the one-time-warning tests would pass or fail depending on order
    (rules/coding-standards.md §13.1 G3: no shared fixed paths, no order
    dependence).
    """
    monkeypatch.setattr(spine, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(spine, "repo_root", lambda: str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    monkeypatch.delenv("ZETETIC_SPINE_WARN", raising=False)
    monkeypatch.delenv("ZETETIC_SPINE_BLOCK", raising=False)
    return tmp_path


def _run_main(monkeypatch, payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    with pytest.raises(SystemExit) as excinfo:
        spine.main()
    return excinfo.value.code


def _transcript(tmp_path, body: str) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text(body)
    return str(path)


# ── terminal signals ─────────────────────────────────────────────────────────

def test_allow_exits_zero_silently(capsys):
    with pytest.raises(SystemExit) as excinfo:
        spine.allow()
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_block_writes_a_block_decision(capsys):
    with pytest.raises(SystemExit) as excinfo:
        spine.block("why")
    assert excinfo.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "block", "reason": "why"}


def test_warn_writes_to_stderr_only(capsys):
    with pytest.raises(SystemExit):
        spine.warn("heads up")
    captured = capsys.readouterr()
    assert captured.err.strip() == "heads up" and captured.out == ""


def test_note_names_the_tool_and_the_exception(capsys):
    spine._note("state write failed", OSError("disk"))
    err = capsys.readouterr().err
    assert "[zetetic-spine]" in err and "OSError" in err and "disk" in err


# ── repo_root ────────────────────────────────────────────────────────────────

def test_repo_root_uses_git_toplevel(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="/repo\n"))
    assert _REAL_REPO_ROOT() == "/repo"


def test_repo_root_falls_back_to_cwd_when_git_fails(monkeypatch):
    def _raise(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _REAL_REPO_ROOT() == os.getcwd()


def test_repo_root_falls_back_to_cwd_on_empty_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=" \n"))
    assert _REAL_REPO_ROOT() == os.getcwd()


# ── read_tail ────────────────────────────────────────────────────────────────

def test_read_tail_returns_the_whole_file_when_small(isolate_state):
    assert spine.read_tail(_transcript(isolate_state, "hello")) == "hello"


def test_read_tail_reads_only_the_end_of_a_large_file(isolate_state, monkeypatch):
    """The bound that keeps this hook cheap on a multi-hundred-MB transcript."""
    monkeypatch.setattr(spine, "TAIL_BYTES", 10)
    path = _transcript(isolate_state, "0123456789ABCDEFGHIJ")
    assert spine.read_tail(path) == "ABCDEFGHIJ"


@pytest.mark.parametrize("path", ["", None, 42, [], {"a": 1}])
def test_read_tail_returns_empty_for_a_non_path(path):
    """The hook is handed whatever the host serialised; a non-string is not a path."""
    assert spine.read_tail(path) == ""


def test_read_tail_returns_empty_when_the_file_is_missing(isolate_state):
    assert spine.read_tail(str(isolate_state / "nope.jsonl")) == ""


def test_read_tail_decodes_invalid_utf8_leniently(isolate_state):
    path = isolate_state / "t.jsonl"
    path.write_bytes(b"\xff\xfe ok")
    assert "ok" in spine.read_tail(str(path))


# ── spine_unmet ──────────────────────────────────────────────────────────────

def test_spine_is_not_triggered_without_a_change():
    """No claim/state change this window means the spine was not owed."""
    assert spine.spine_unmet(RECALL) is False
    assert spine.spine_unmet("") is False


def test_spine_is_unmet_when_a_change_has_no_evidence():
    assert spine.spine_unmet(EDIT) is True


def test_spine_is_met_when_recall_accompanies_a_change():
    assert spine.spine_unmet(EDIT + RECALL) is False


def test_spine_is_met_when_a_memory_read_accompanies_a_change():
    tail = EDIT + '{"command": "memory-tool.sh view /memories/x"}'
    assert spine.spine_unmet(tail) is False


def test_a_memory_write_is_not_evidence_of_recall():
    """create/str_replace are the remember beat, not the recall beat."""
    tail = EDIT + '{"command": "memory-tool.sh create /memories/x body"}'
    assert spine.spine_unmet(tail) is True


# ── one-time warn state ──────────────────────────────────────────────────────

def test_warn_state_starts_unset_and_is_recorded(isolate_state):
    assert spine.already_warned("s1") is False
    spine.mark_warned("s1")
    assert spine.already_warned("s1") is True


def test_warn_state_is_per_session(isolate_state):
    spine.mark_warned("s1")
    assert spine.already_warned("s2") is False


def test_mark_warned_reports_but_survives_an_unwritable_state_dir(
    isolate_state, monkeypatch, capsys
):
    """Degraded, not silent: the reminder may repeat, and the note says so."""
    monkeypatch.setattr(spine, "STATE_DIR", str(isolate_state / "missing-dir"))
    spine.mark_warned("s1")  # must not raise
    assert "warn-state write failed" in capsys.readouterr().err


# ── main: fail-open routes ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["", "  ", "not json", '{"a":'])
def test_main_allows_on_unparseable_stdin(monkeypatch, raw, capsys):
    assert _run_main(monkeypatch, raw) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("raw", ["[]", "42", "null", "true", '"s"'])
def test_main_allows_on_valid_non_object_json(monkeypatch, raw):
    assert _run_main(monkeypatch, raw) == 0


def test_main_allows_when_stdin_read_raises(monkeypatch):
    class Exploding:
        def read(self):
            raise OSError("gone")

    monkeypatch.setattr(sys, "stdin", Exploding())
    with pytest.raises(SystemExit) as excinfo:
        spine.main()
    assert excinfo.value.code == 0


def test_main_allows_during_a_forced_continuation(monkeypatch, isolate_state, capsys):
    """Loop safety: stop_hook_active must not produce another block."""
    payload = {"stop_hook_active": True,
               "transcript_path": _transcript(isolate_state, EDIT)}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_main_allows_when_the_spine_is_satisfied(monkeypatch, isolate_state, capsys):
    payload = {"session_id": "s", "transcript_path": _transcript(isolate_state, EDIT + RECALL)}
    assert _run_main(monkeypatch, payload) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_main_allows_when_the_transcript_is_unreadable(monkeypatch, isolate_state):
    """An absent transcript reads as empty, which cannot trigger the gate."""
    payload = {"session_id": "s", "transcript_path": str(isolate_state / "nope")}
    assert _run_main(monkeypatch, payload) == 0


# ── main: WARN tier (default, one-time) ──────────────────────────────────────

def test_warn_tier_reminds_once_and_does_not_block(monkeypatch, isolate_state, capsys):
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    assert _run_main(monkeypatch, payload) == 0
    captured = capsys.readouterr()
    assert captured.out == "", "the default tier must never emit a block decision"
    assert "Zetetic spine" in captured.err
    assert "non-blocking" in captured.err
    assert "ZETETIC_SPINE_WARN=off" in captured.err


def test_warn_tier_fires_only_once_per_session(monkeypatch, isolate_state, capsys):
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    _run_main(monkeypatch, payload)
    capsys.readouterr()
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().err == "", "a repeat reminder is noise, not a signal"


def test_warn_tier_fires_again_for_a_different_session(monkeypatch, isolate_state, capsys):
    transcript = _transcript(isolate_state, EDIT)
    _run_main(monkeypatch, {"session_id": "s1", "transcript_path": transcript})
    capsys.readouterr()
    _run_main(monkeypatch, {"session_id": "s2", "transcript_path": transcript})
    assert "Zetetic spine" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["off", "OFF", "Off"])
def test_warn_tier_is_suppressible(monkeypatch, isolate_state, capsys, value):
    monkeypatch.setenv("ZETETIC_SPINE_WARN", value)
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().err == ""


def test_a_missing_session_id_still_warns(monkeypatch, isolate_state, capsys):
    payload = {"transcript_path": _transcript(isolate_state, EDIT)}
    assert _run_main(monkeypatch, payload) == 0
    assert "Zetetic spine" in capsys.readouterr().err


# ── main: BLOCK tier (opt-in) ────────────────────────────────────────────────

def test_marker_file_makes_the_gate_blocking(monkeypatch, isolate_state, capsys):
    (isolate_state / "root" / ".zetetic-spine.json").write_text("{}")
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    assert _run_main(monkeypatch, payload) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert ".zetetic-spine.json active" in decision["reason"]


def test_env_opt_in_makes_the_gate_blocking(monkeypatch, isolate_state, capsys):
    monkeypatch.setenv("ZETETIC_SPINE_BLOCK", "on")
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    _run_main(monkeypatch, payload)
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_block_tier_does_not_fire_when_the_spine_is_met(
    monkeypatch, isolate_state, capsys
):
    monkeypatch.setenv("ZETETIC_SPINE_BLOCK", "on")
    payload = {"session_id": "s1",
               "transcript_path": _transcript(isolate_state, EDIT + RECALL)}
    assert _run_main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""


def test_blocking_does_not_consume_the_one_time_warn_state(
    monkeypatch, isolate_state, capsys
):
    """Removing the marker must leave the warning still available to fire."""
    monkeypatch.setenv("ZETETIC_SPINE_BLOCK", "on")
    payload = {"session_id": "s1", "transcript_path": _transcript(isolate_state, EDIT)}
    _run_main(monkeypatch, payload)
    capsys.readouterr()
    assert spine.already_warned("s1") is False


def test_the_reason_names_the_four_spine_beats():
    """The reminder has to be actionable, not just a complaint."""
    for beat in ("recall", "evidence", "adversarial-verify", "remember"):
        assert beat in spine.REASON
