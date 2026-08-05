"""Unit tests for tools.goa.assemble_fixture — building/growing
external_testbase_v1.json without ever storing raw corpus text, and refusing
to change an already-frozen row (the same append-only contract
fixture_freeze_gate.py enforces at the CI layer)."""
from __future__ import annotations

import pytest

from tools.goa.assemble_fixture import assemble_rows, build_row, merge_append_only
from tools.goa.candidate_schema import Candidate, Provenance


def _candidate(case_id: str, text: str = "some invented question text") -> Candidate:
    return Candidate(
        case_id=case_id,
        shape="causal-audit",
        corpus="stackexchange",
        text=text,
        provenance=Provenance(
            corpus="stackexchange",
            source_id=case_id,
            license="CC BY-SA 4.0",
            site_or_dataset="stats.stackexchange.com",
            tags=("causality",),
            score=5,
        ),
    )


def test_build_row_never_contains_raw_text():
    row = build_row(_candidate("a1"), {"case_id": "a1", "label": "causal-audit"}, "exact-agreement")
    assert "text" not in row
    assert row["features"]["word_count"] == len("some invented question text".split())
    assert row["source_id"] == "a1"
    assert row["adjudication_trail"] == "exact-agreement"


def test_assemble_rows_joins_candidates_agreed_and_adjudicated():
    candidates = [_candidate("a1"), _candidate("a2")]
    agreed = [{"case_id": "a1", "label": "causal-audit"}]
    adjudicated = [{"case_id": "a2", "label": "estimation"}]
    rows = assemble_rows(candidates, agreed, adjudicated)
    by_id = {r["case_id"]: r for r in rows}
    assert by_id["a1"]["adjudication_trail"] == "exact-agreement"
    assert by_id["a2"]["adjudication_trail"] == "3rd-pass 2-of-3"
    assert by_id["a2"]["label"] == "estimation"


def test_assemble_rows_raises_when_provenance_is_missing():
    with pytest.raises(ValueError, match="no matching candidate"):
        assemble_rows([], [{"case_id": "missing", "label": "x"}], [])


def test_merge_append_only_adds_new_rows():
    existing = [{"case_id": "a1", "label": "causal-audit"}]
    new = [{"case_id": "a2", "label": "estimation"}]
    merged = merge_append_only(existing, new)
    assert {r["case_id"] for r in merged} == {"a1", "a2"}


def test_merge_append_only_is_idempotent_for_identical_rows():
    existing = [{"case_id": "a1", "label": "causal-audit"}]
    merged = merge_append_only(existing, [{"case_id": "a1", "label": "causal-audit"}])
    assert merged == existing


def test_merge_append_only_rejects_a_changed_existing_row():
    existing = [{"case_id": "a1", "label": "causal-audit"}]
    with pytest.raises(ValueError, match="append-only violation"):
        merge_append_only(existing, [{"case_id": "a1", "label": "estimation"}])
