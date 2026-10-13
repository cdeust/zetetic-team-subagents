"""Subagent reflection ledger: unreadable and undecodable files, rows of older releases (#153)."""
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
import gates_jsonl
import reflection_ledger as ledger


def _make_ledger_unreadable(reflection_repo: Path) -> None:
    path = Path(ledger.ledger_path(str(reflection_repo)))
    path.mkdir(parents=True)  # a directory where the file should be: IsADirectoryError on open


def test_C_an_unreadable_ledger_is_a_ledger_error_naming_the_path(reflection_repo):
    _make_ledger_unreadable(reflection_repo)
    path = ledger.ledger_path(str(reflection_repo))
    with pytest.raises(gates_jsonl.LedgerError, match="cannot read the ledger") as caught:
        gates_jsonl.read_rows(path)
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


# A ledger written by release 2.43.0: its hook appended a Hindsight outcome
# row {"hindsight_for": <agent_id>, ...} after each pending row, also after a lift.
LEGACY_OUTCOME = {"status": "not_configured", "detail": "no Hindsight config", "bank": None,
                  "document_id": None}


def test_a_ledger_with_2_43_0_outcome_rows_reads_as_its_pending_rows(reflection_repo, schedule):
    path = _pending_row(reflection_repo, schedule)
    _pending_row(reflection_repo, schedule, agent_id="d4e5f6")
    for agent_id in ("a1b2c3", "d4e5f6", "ghost"):
        gates_jsonl.append_row(path, {"hindsight_for": agent_id, "hindsight": LEGACY_OUTCOME})
    ledger.lift(path, "d4e5f6", 7)
    gates_jsonl.append_row(path, {"hindsight_for": "d4e5f6", "hindsight": LEGACY_OUTCOME})
    assert [r["agent_id"] for r in ledger.pending(path)] == ["a1b2c3"]
    assert ledger.lift(path, "a1b2c3", 8)["memory_id"] == 8
    with pytest.raises(ledger.LiftRefused, match="no pending reflection"):
        ledger.lift(path, "ghost", 9)
