"""Unit tests for tools.goa.labeler_schema, build_labeler_batches, and
validate_labeler_output — the labeler I/O preparation/validation half of the
curation pipeline (no LLM calls; the labeler agents run separately)."""
from __future__ import annotations

import json

from tools.goa.build_labeler_batches import build_blind_batch
from tools.goa.candidate_schema import Candidate, Provenance, write_jsonl
from tools.goa.labeler_schema import validate_label_row
from tools.goa.validate_labeler_output import validate_file


def _candidate(case_id: str) -> Candidate:
    return Candidate(
        case_id=case_id,
        shape="causal-audit",
        corpus="stackexchange",
        text=f"text for {case_id}",
        provenance=Provenance(
            corpus="stackexchange",
            source_id=case_id,
            license="CC BY-SA 4.0",
            site_or_dataset="stats.stackexchange.com",
            tags=("causality",),
        ),
    )


def _valid_label_row(case_id: str = "abc") -> dict:
    return {"case_id": case_id, "label": "causal-audit", "confidence": 0.8, "rationale": "clear causal claim"}


def test_validate_label_row_accepts_valid_row():
    assert validate_label_row(_valid_label_row()) == []


def test_validate_label_row_flags_confidence_out_of_range():
    row = _valid_label_row()
    row["confidence"] = 1.5
    assert "confidence-out-of-range:[0,1]" in validate_label_row(row)


def test_validate_label_row_flags_non_numeric_confidence():
    row = _valid_label_row()
    row["confidence"] = "high"
    assert "missing-or-non-numeric:confidence" in validate_label_row(row)


def test_validate_label_row_rejects_boolean_confidence():
    row = _valid_label_row()
    row["confidence"] = True
    assert "missing-or-non-numeric:confidence" in validate_label_row(row)


def test_validate_label_row_flags_unexpected_fields():
    row = _valid_label_row()
    row["site"] = "stats.stackexchange.com"  # provenance leak — must never appear
    assert any(e.startswith("unexpected-fields") for e in validate_label_row(row))


def test_validate_label_row_flags_missing_rationale():
    row = _valid_label_row()
    del row["rationale"]
    assert "missing-or-empty:rationale" in validate_label_row(row)


def test_build_blind_batch_strips_provenance(tmp_path):
    candidates_path = tmp_path / "candidates.jsonl"
    write_jsonl(candidates_path, [_candidate("a1"), _candidate("a2")])
    rows, bad_lines = build_blind_batch(candidates_path, restrict_to=None)
    assert bad_lines == []
    assert rows == [{"case_id": "a1", "text": "text for a1"}, {"case_id": "a2", "text": "text for a2"}]
    for row in rows:
        assert "site" not in row and "tags" not in row and "shape" not in row


def test_build_blind_batch_restricts_to_given_case_ids(tmp_path):
    candidates_path = tmp_path / "candidates.jsonl"
    write_jsonl(candidates_path, [_candidate("a1"), _candidate("a2"), _candidate("a3")])
    rows, _ = build_blind_batch(candidates_path, restrict_to={"a2"})
    assert rows == [{"case_id": "a2", "text": "text for a2"}]


def test_validate_file_reports_line_numbers_for_invalid_rows(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(
        "\n".join([json.dumps(_valid_label_row("a1")), json.dumps({"case_id": "a2"}), ""]),
        encoding="utf-8",
    )
    problems = validate_file(path)
    assert len(problems) == 1
    assert problems[0][0] == 2


def test_validate_file_flags_duplicate_case_id(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(
        "\n".join([json.dumps(_valid_label_row("a1")), json.dumps(_valid_label_row("a1"))]),
        encoding="utf-8",
    )
    problems = validate_file(path)
    assert len(problems) == 1
    assert "duplicate-case-id" in problems[0][1]


def test_validate_file_all_valid_returns_no_problems(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(_valid_label_row("a1")), encoding="utf-8")
    assert validate_file(path) == []
