"""Unit tests for tools.goa.readonly_slice_reference — SWE-bench/Defects4J
reference-only rows (source_id + license + locally computed features, never
the operator's local raw issue/bug-report text)."""
from __future__ import annotations

import pytest

from tools.goa.readonly_slice_reference import build_reference_row, build_references, validate_input_row


def _row(**overrides) -> dict:
    base = {"source_id": "django__django-1", "license": "BSD-3-Clause", "corpus": "swebench", "text": "an issue body"}
    base.update(overrides)
    return base


def test_validate_input_row_accepts_valid_row():
    assert validate_input_row(_row()) == []


def test_validate_input_row_flags_unknown_corpus():
    errors = validate_input_row(_row(corpus="github-issues"))
    assert any("unknown-corpus" in e for e in errors)


@pytest.mark.parametrize("field_name", ["source_id", "license", "corpus", "text"])
def test_validate_input_row_flags_missing_field(field_name):
    row = _row()
    row[field_name] = ""
    assert f"missing-or-empty:{field_name}" in validate_input_row(row)


def test_build_reference_row_never_contains_the_text_field():
    reference = build_reference_row(_row())
    assert "text" not in reference
    assert reference["source_id"] == "django__django-1"
    assert reference["features"]["word_count"] == 3


def test_build_references_skips_invalid_rows_and_reports_them():
    rows = [_row(), _row(source_id="")]
    references, bad_rows = build_references(rows)
    assert len(references) == 1
    assert len(bad_rows) == 1
    assert bad_rows[0][0] == 2
