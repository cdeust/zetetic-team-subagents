"""Subagent reflection ledger: unreadable and undecodable files, outcome-line merge edges (#153)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reflection_support import (
    SESSION,
    event,
    make_transcript,
    rows,
    run_hook,
    start_hook,
    stop_event,
    stop_hook,
)
import reflection_ledger as ledger

pytestmark = pytest.mark.usefixtures("no_real_hindsight")


def _make_ledger_unreadable(reflection_repo: Path) -> None:
    path = Path(ledger.ledger_path(str(reflection_repo)))
    path.mkdir(parents=True)  # a directory where the file should be: IsADirectoryError on open


def test_C_an_unreadable_ledger_is_a_ledger_error_naming_the_path(reflection_repo):
    _make_ledger_unreadable(reflection_repo)
    path = ledger.ledger_path(str(reflection_repo))
    with pytest.raises(ledger.LedgerError, match="cannot read the ledger") as caught:
        ledger.read_rows(path)
    assert path in str(caught.value)


def test_C_both_hooks_report_an_unreadable_ledger_and_exit_zero(reflection_repo, tmp_path, monkeypatch, capsys):
    _make_ledger_unreadable(reflection_repo)
    payload = event(reflection_repo, make_transcript(tmp_path), agent_id="a1b2c3", agent_type="engineer")
    code, _, err = run_hook(start_hook, payload, monkeypatch, capsys)
    assert code == 0 and "ledger NOT written" in err and "cannot read the ledger" in err
    code, out, err = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    assert code == 0 and out == "" and "ledger unreadable" in err and "cannot read the ledger" in err


def _append_bytes(reflection_repo, data: bytes) -> None:
    with open(ledger.ledger_path(str(reflection_repo)), "ab") as fh:
        fh.write(data)


def test_C_an_undecodable_line_is_skipped_like_a_torn_one_and_valid_rows_survive(reflection_repo, schedule):
    schedule("a1b2c3")
    _append_bytes(reflection_repo, b"\xff\xfe{bad\n")
    schedule("d4e5f6")
    assert [r["agent_id"] for r in ledger.pending(ledger.ledger_path(str(reflection_repo)))] == ["a1b2c3", "d4e5f6"]


def test_C_both_hooks_survive_an_undecodable_ledger_line(reflection_repo, monkeypatch, capsys, schedule):
    schedule("a1b2c3")
    _append_bytes(reflection_repo, b"\xff\xfe{bad\n")
    code, out, _ = run_hook(stop_hook, stop_event(reflection_repo), monkeypatch, capsys)
    assert code == 0 and json.loads(out)["decision"] == "block"  # still enforcing, rc 0
    schedule("d4e5f6")  # runs the SubagentStop hook, which would raise on an undecodable ledger
    assert {r["agent_id"] for r in rows(reflection_repo)} == {"a1b2c3", "d4e5f6"}


def _pending_row(reflection_repo, schedule, agent_id="a1b2c3"):
    schedule(agent_id)
    return ledger.ledger_path(str(reflection_repo))


def test_merge_an_outcome_for_an_unknown_agent_is_ignored(reflection_repo, schedule):
    path = _pending_row(reflection_repo, schedule)
    ledger.record_hindsight(path, "ghost", {"status": "retained", "detail": "x"})
    (row,) = ledger.pending(path)
    assert row["agent_id"] == "a1b2c3" and row["hindsight"]["status"] == "not_configured"


def test_merge_duplicate_outcomes_last_line_wins(reflection_repo, schedule):
    path = _pending_row(reflection_repo, schedule)
    ledger.record_hindsight(path, "a1b2c3", {"status": "retained", "detail": "first"})
    ledger.record_hindsight(path, "a1b2c3", {"status": "error", "detail": "second"})
    (row,) = ledger.pending(path)
    assert row["hindsight"]["detail"] == "second"


def test_merge_an_outcome_line_before_its_pending_row_still_attaches(reflection_repo):
    path = ledger.ledger_path(str(reflection_repo))
    ledger.record_hindsight(path, "a1b2c3", {"status": "retained", "detail": "early"})
    assert ledger.append_pending(path, {"agent_id": "a1b2c3", "session_id": SESSION,
                                        "hindsight": {"status": "pending", "detail": "placeholder"}})
    (row,) = ledger.pending(path)
    assert row["hindsight"]["detail"] == "early"


def test_merge_an_outcome_for_a_lifted_row_does_not_resurrect_it(reflection_repo, schedule):
    path = _pending_row(reflection_repo, schedule)
    ledger.lift(path, "a1b2c3", 7)
    ledger.record_hindsight(path, "a1b2c3", {"status": "retained", "detail": "late"})
    assert ledger.pending(path) == []
    with pytest.raises(ledger.LiftRefused, match="already lifted"):
        ledger.lift(path, "a1b2c3", 8)
