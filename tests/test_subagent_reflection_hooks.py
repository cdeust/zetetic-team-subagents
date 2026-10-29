"""Subagent reflection, SubagentStop side: the pending row, payload shapes, ordering (#153)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from reflection_support import (
    REPO_ROOT,
    SESSION,
    _assistant,
    event,
    make_transcript,
    raw_rows,
    rows,
    run_hook,
    start_hook,
)
import reflection_ledger as ledger
import reflection_subagent


def test_payload_with_agent_type_records_pending_row(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta={"agentType": "from-meta", "description": "fix parser"})
    code, _, err = run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3",
                                              agent_type="general-purpose"),
                            monkeypatch, capsys)
    assert code == 0
    (row,) = rows(reflection_repo)
    assert row["agent_id"] == "a1b2c3"
    assert row["agent_type"] == "general-purpose"
    assert row["description"] == "fix parser"
    assert row["transcript_path"] == str(transcript)
    assert row["session_id"] == SESSION
    assert row["excerpt"] == "Done: fixed the bug in parser.py"
    assert "pending reflection recorded" in err
    assert not any("agent_type taken from meta.json" in n for n in row["notes"])


def test_payload_without_agent_type_falls_back_to_meta_json(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta={"agentType": "claude-code-guide", "description": "d"})
    _, _, err = run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    (row,) = rows(reflection_repo)
    assert row["agent_type"] == "claude-code-guide"
    assert "agent_type taken from meta.json" in row["notes"]
    assert "agent_type taken from meta.json" in err


def test_agent_id_and_type_recovered_from_the_transcript_file_alone(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, agent_id="zz9", meta={"agentType": "reviewer"})
    run_hook(start_hook, event(reflection_repo, None, transcript_path=str(transcript)), monkeypatch, capsys)
    (row,) = rows(reflection_repo)
    assert (row["agent_id"], row["agent_type"]) == ("zz9", "reviewer")
    assert "agent_id taken from the transcript file name" in row["notes"]
    assert not any("not identified" in n for n in row["notes"])


def test_no_agent_type_anywhere_is_recorded_as_unknown_and_said_so(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, meta=None)
    _, _, err = run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    (row,) = rows(reflection_repo)
    assert row["agent_type"] == "unknown"
    assert "agent_type absent from the payload and from meta.json" in err


def test_unidentifiable_event_writes_nothing_and_says_so(reflection_repo, monkeypatch, capsys):
    code, _, err = run_hook(start_hook, event(reflection_repo, None), monkeypatch, capsys)
    assert code == 0
    assert "cannot identify the subagent" in err
    assert rows(reflection_repo) == []


def test_final_message_falls_back_to_last_text_then_payload(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, handback=None)
    run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3"), monkeypatch, capsys)
    assert rows(reflection_repo)[0]["excerpt"] == "working on it"
    empty = tmp_path / "empty"
    empty.mkdir()
    bare = make_transcript(empty, agent_id="b2", handback=None)
    bare.write_text("", encoding="utf-8")
    run_hook(start_hook, event(reflection_repo, bare, agent_id="b2", last_assistant_message="from payload"),
             monkeypatch, capsys)
    assert rows(reflection_repo)[1]["excerpt"] == "from payload"


def test_the_last_handback_wins_and_an_overlong_one_is_cut_with_a_marker(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path, handback="first report")
    long_text = "x" * (reflection_subagent.MAX_EXCERPT_CHARS + 10)
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(_assistant("m3", {"type": "tool_use", "name": "SubagentHandback",
                                   "input": {"message": long_text}}) + "\n")
    run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3", agent_type="t"), monkeypatch, capsys)
    excerpt = rows(reflection_repo)[0]["excerpt"]
    assert excerpt.startswith("x" * reflection_subagent.MAX_EXCERPT_CHARS)
    assert excerpt.endswith(f"[... cut at {reflection_subagent.MAX_EXCERPT_CHARS} characters]")
    assert "first report" not in excerpt


def test_refiring_for_the_same_agent_does_not_duplicate(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path)
    payload = event(reflection_repo, transcript, agent_id="a1b2c3", agent_type="t")
    run_hook(start_hook, payload, monkeypatch, capsys)
    _, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert len(rows(reflection_repo)) == 1
    assert "already in the ledger" in err


def test_a_later_stop_with_a_newer_final_message_updates_the_excerpt(reflection_repo, tmp_path, monkeypatch, capsys):
    """The cycle gate can block a subagent's first stop; its final stop carries
    the report the reflection must quote, so the newer excerpt is recorded."""
    transcript = make_transcript(tmp_path, handback="first report")
    payload = event(reflection_repo, transcript, agent_id="a1b2c3", agent_type="t")
    run_hook(start_hook, payload, monkeypatch, capsys)
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(_assistant("m3", {"type": "tool_use", "name": "SubagentHandback",
                                   "input": {"message": "final report"}}) + "\n")
    _, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert "newer final message recorded" in err
    (row,) = ledger.pending(ledger.ledger_path(str(reflection_repo)))
    assert row["excerpt"] == "final report"
    run_hook(start_hook, payload, monkeypatch, capsys)  # same message again: nothing appended
    assert len([r for r in raw_rows(reflection_repo) if "excerpt_for" in r]) == 1


def test_a_tool_internal_run_without_transcript_or_meta_is_reported_not_scheduled(
        reflection_repo, tmp_path, monkeypatch, capsys):
    parent = tmp_path / "proj" / f"{SESSION}.jsonl"
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.write_text("", encoding="utf-8")
    payload = event(reflection_repo, None, agent_id="af011bb9", transcript_path=str(parent),
                    last_assistant_message="Fetching hooks documentation page")
    code, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert code == 0 and "not a delegated agent" in err
    assert rows(reflection_repo) == []


def test_a_typed_subagent_whose_transcript_was_not_located_is_still_scheduled(
        reflection_repo, tmp_path, monkeypatch, capsys):
    parent = tmp_path / "proj" / f"{SESSION}.jsonl"
    parent.parent.mkdir(parents=True, exist_ok=True)
    parent.write_text("", encoding="utf-8")
    payload = event(reflection_repo, None, agent_id="b2c3d4e5", agent_type="Plan",
                    transcript_path=str(parent), last_assistant_message="VERDICT: APPROVE")
    code, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert code == 0 and "not a delegated agent" not in err
    assert "subagent transcript not identified" in err
    (row,) = rows(reflection_repo)
    assert row["agent_id"] == "b2c3d4e5" and row["agent_type"] == "Plan"


def test_the_ledger_is_owner_only_because_rows_carry_transcript_excerpts(reflection_repo, tmp_path, monkeypatch, capsys):
    transcript = make_transcript(tmp_path)
    run_hook(start_hook, event(reflection_repo, transcript, agent_id="a1b2c3", agent_type="t"), monkeypatch, capsys)
    path = Path(ledger.ledger_path(str(reflection_repo)))
    assert path.stat().st_mode & 0o777 == 0o600


def test_outside_a_git_repo_the_missing_ledger_is_reported(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    transcript = make_transcript(tmp_path)
    code, _, err = run_hook(start_hook, event(plain, transcript, agent_id="a1b2c3", agent_type="t"),
                            monkeypatch, capsys)
    assert code == 0
    assert "ledger NOT written" in err


def test_hook_script_runs_as_a_subprocess(reflection_repo, tmp_path):
    transcript = make_transcript(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "subagent-stop-reflection.py")],
        input=json.dumps(event(reflection_repo, transcript, agent_id="a1b2c3", agent_type="t")),
        capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0
    assert "pending reflection recorded" in proc.stderr
    assert len(rows(reflection_repo)) == 1


def test_both_hooks_are_registered_for_their_events():
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    def commands(event_name: str) -> str:
        return json.dumps(hooks[event_name])

    assert "subagent-stop-reflection.py" in commands("SubagentStop")
    assert "stop-reflection-gate.py" in commands("Stop")


def test_the_hook_writes_the_pending_row_and_nothing_else(reflection_repo, tmp_path, monkeypatch, capsys):
    payload = event(reflection_repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="general-purpose")
    _, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    (row,) = raw_rows(reflection_repo)
    assert row["agent_id"] == "a1b2c3" and "hindsight" not in row
    assert "hindsight" not in err.lower()


def test_B_a_subagent_event_without_session_id_is_noted_on_the_row(reflection_repo, tmp_path, monkeypatch, capsys):
    payload = event(reflection_repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="general-purpose")
    del payload["session_id"]
    _, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    (row,) = rows(reflection_repo)
    assert row["session_id"] == ""
    assert any("no session_id" in n for n in row["notes"])
    assert "no session_id" in err
