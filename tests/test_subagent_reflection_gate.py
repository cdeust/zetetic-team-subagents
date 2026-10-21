"""Subagent reflection, Stop side: the gate, attribution by session, lift needs evidence (#153)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reflection_support import (
    event,
    make_transcript,
    rows,
    run_hook,
    start_hook,
    stop_event,
    stop_hook,
)
import reflection_ledger as ledger


def test_stop_blocks_while_pending_and_names_the_procedure(reflection_repo, monkeypatch, capsys, schedule):
    schedule()
    code, out, _ = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    reason = decision["reason"]
    for needle in ("lesson-candidate", "agent_topic", "a1b2c3", "general-purpose", "--memory-id",
                   "reflection_ledger.py", "Quote the transcript lines"):
        assert needle in reason


def test_stop_allows_after_lift_with_a_memory_id(reflection_repo, monkeypatch, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(reflection_repo), "lift", "a1b2c3", "--memory-id", "4242"]) == 0
    assert "lifted a1b2c3 with Cortex memory 4242" in capsys.readouterr().out
    _, out, _ = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    assert out == ""
    lift_row = [r for r in rows(reflection_repo) if "lift" in r][0]
    assert lift_row["memory_id"] == 4242


def test_stop_is_not_reblocked_in_a_forced_continuation_but_says_so(reflection_repo, monkeypatch, capsys, schedule):
    schedule()
    _, out, err = run_hook(stop_hook, stop_event(reflection_repo, stop_hook_active=True), monkeypatch, capsys)
    assert out == ""
    assert "still pending" in err and "a1b2c3" in err


def test_another_sessions_pending_reflection_does_not_block_but_is_reported(reflection_repo, monkeypatch, capsys, schedule):
    schedule(session="sess-B")
    _, out, err = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    assert out == ""
    assert "1 pending reflection(s) belong to other sessions" in err


def test_stop_with_nothing_pending_or_no_repo_is_silent(reflection_repo, tmp_path, monkeypatch, capsys):
    assert run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)[1:] == ("", "")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run_hook(stop_hook, stop_event(plain), monkeypatch, capsys)[1:] == ("", "")


def test_stop_lists_at_most_the_cap_and_points_at_the_list_command(reflection_repo, monkeypatch, capsys, schedule):
    for n in range(stop_hook.MAX_LISTED + 2):
        schedule(agent_id=f"ag{n}")
    reason = json.loads(run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)[1])["reason"]
    assert f"{stop_hook.MAX_LISTED + 2} subagent reflection(s) pending" in reason
    assert "(+2 more" in reason and f"ag{stop_hook.MAX_LISTED + 1}" not in reason


@pytest.mark.parametrize("extra", [[], ["--memory-id", "0"], ["--memory-id", "-3"],
                                   ["--memory-id", "abc"], ["--memory-id", "1.5"]])
def test_lift_refuses_without_valid_evidence_and_leaves_the_ledger_untouched(reflection_repo, capsys, extra, schedule):
    schedule()
    before = ledger.ledger_path(str(reflection_repo))
    size = Path(before).stat().st_size
    assert ledger.main(["--cwd", str(reflection_repo), "lift", "a1b2c3", *extra]) == 2
    assert "refusing to lift without evidence" in capsys.readouterr().err
    assert Path(before).stat().st_size == size
    assert [r["agent_id"] for r in ledger.pending(before)] == ["a1b2c3"]


def test_a_boolean_is_not_a_memory_id(reflection_repo, schedule):
    schedule()
    with pytest.raises(ledger.LiftRefused):
        ledger.lift(ledger.ledger_path(str(reflection_repo)), "a1b2c3", True)


def test_lift_refuses_unknown_and_already_lifted_agents(reflection_repo, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(reflection_repo), "lift", "nope", "--memory-id", "7"]) == 2
    assert "no pending reflection for agent nope" in capsys.readouterr().err
    assert ledger.main(["--cwd", str(reflection_repo), "lift", "a1b2c3", "--memory-id", "7"]) == 0
    assert ledger.main(["--cwd", str(reflection_repo), "lift", "a1b2c3", "--memory-id", "8"]) == 2
    assert "already lifted" in capsys.readouterr().err


def test_list_command_prints_pending_entries(reflection_repo, capsys, schedule):
    schedule()
    assert ledger.main(["--cwd", str(reflection_repo), "list"]) == 0
    assert capsys.readouterr().out.startswith("a1b2c3\tgeneral-purpose")


def test_B_a_row_without_session_id_blocks_and_is_called_unattributed(
        reflection_repo, tmp_path, monkeypatch, capsys):
    payload = event(reflection_repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="general-purpose")
    del payload["session_id"]
    run_hook(start_hook, payload, monkeypatch, capsys)
    _, out, err = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    decision = json.loads(out)
    assert decision["decision"] == "block" and "a1b2c3" in decision["reason"]
    assert "unattributed" in err and "unattributed" in decision["reason"]
    assert "belong to other sessions" not in err


def test_B_a_stop_event_without_session_id_blocks_on_all_rows_and_says_why(
        reflection_repo, monkeypatch, capsys, schedule):
    schedule(session="sess-B")
    event_without_session = stop_event(reflection_repo)
    del event_without_session["session_id"]
    _, out, err = run_hook(stop_hook, event_without_session, monkeypatch, capsys)
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "Stop payload carries no session_id" in err
    assert "no session_id" in decision["reason"]
