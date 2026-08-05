"""Unit tests for tools.goa.candidate_schema — the shared candidate record.

Imported under its fully-qualified package path (tools.goa.candidate_schema),
matching the mutmut trampoline convention used across this repo's test suite
(see test_manifest_gate.py's docstring for why bare imports break mutation
scoring).
"""
from __future__ import annotations

import json

import pytest

from tools.goa.candidate_schema import (
    Candidate,
    Provenance,
    candidate_from_dict,
    read_jsonl,
    validate_candidate_dict,
    write_jsonl,
)


def _valid_row() -> dict:
    return {
        "case_id": "abc123",
        "shape": "causal-audit",
        "corpus": "stackexchange",
        "text": "Some invented question text.",
        "provenance": {
            "corpus": "stackexchange",
            "source_id": "42",
            "license": "CC BY-SA 4.0",
            "site_or_dataset": "stats.stackexchange.com",
            "tags": ["causality"],
            "score": 5,
        },
    }


def test_validate_candidate_dict_accepts_valid_row():
    assert validate_candidate_dict(_valid_row()) == []


@pytest.mark.parametrize("field_name", ["case_id", "shape", "corpus", "text"])
def test_validate_candidate_dict_flags_missing_required_field(field_name):
    row = _valid_row()
    del row[field_name]
    errors = validate_candidate_dict(row)
    assert f"missing-or-empty:{field_name}" in errors


def test_validate_candidate_dict_flags_missing_provenance():
    row = _valid_row()
    del row["provenance"]
    assert validate_candidate_dict(row) == ["missing-provenance"]


@pytest.mark.parametrize("field_name", ["corpus", "source_id", "license", "site_or_dataset"])
def test_validate_candidate_dict_flags_missing_provenance_field(field_name):
    row = _valid_row()
    del row["provenance"][field_name]
    errors = validate_candidate_dict(row)
    assert f"missing-or-empty:provenance.{field_name}" in errors


def test_candidate_from_dict_round_trips():
    row = _valid_row()
    candidate = candidate_from_dict(row)
    assert candidate.case_id == "abc123"
    assert candidate.provenance.tags == ("causality",)
    assert candidate.to_dict()["provenance"]["source_id"] == "42"


def test_candidate_from_dict_raises_on_invalid_row():
    row = _valid_row()
    del row["text"]
    with pytest.raises(ValueError):
        candidate_from_dict(row)


def test_write_and_read_jsonl_round_trip(tmp_path):
    candidate = candidate_from_dict(_valid_row())
    path = tmp_path / "candidates.jsonl"
    write_jsonl(path, [candidate])
    loaded, bad_lines = read_jsonl(path)
    assert bad_lines == []
    assert len(loaded) == 1
    assert loaded[0].case_id == candidate.case_id


def test_read_jsonl_reports_malformed_and_invalid_lines(tmp_path):
    path = tmp_path / "candidates.jsonl"
    valid_row = _valid_row()
    invalid_row = _valid_row()
    del invalid_row["text"]
    path.write_text(
        "\n".join(
            [
                json.dumps(valid_row),
                "not json at all",
                json.dumps(invalid_row),
                "",
            ]
        ),
        encoding="utf-8",
    )
    loaded, bad_lines = read_jsonl(path)
    assert len(loaded) == 1
    assert len(bad_lines) == 2
    assert bad_lines[0][0] == 2
    assert bad_lines[1][0] == 3


def test_candidate_to_jsonl_row_is_valid_json():
    candidate = Candidate(
        case_id="x",
        shape="estimation",
        corpus="stackexchange",
        text="t",
        provenance=Provenance(corpus="stackexchange", source_id="1", license="CC BY-SA 4.0", site_or_dataset="pm.SE"),
    )
    parsed = json.loads(candidate.to_jsonl_row())
    assert parsed["case_id"] == "x"
