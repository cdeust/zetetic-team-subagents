"""Unit tests for tools.goa.fixture_features — locally-computed features and
the raw-text ban that keeps corpus text out of the committed fixture."""
from __future__ import annotations

from tools.goa.fixture_features import assert_no_raw_text, compute_features


def test_compute_features_counts_words_and_chars():
    features = compute_features("Is this a question?")
    assert features["char_count"] == len("Is this a question?")
    assert features["word_count"] == 4
    assert features["question_mark_count"] == 1


def test_compute_features_empty_text_has_zero_avg_word_length():
    features = compute_features("")
    assert features["word_count"] == 0
    assert features["avg_word_length"] == 0.0


def test_compute_features_detects_code_block():
    assert compute_features("normal text")["contains_code_block"] is False
    assert compute_features("some ```code``` here")["contains_code_block"] is True
    assert compute_features("some <pre>code</pre> here")["contains_code_block"] is True


def test_assert_no_raw_text_passes_clean_row():
    row = {"case_id": "a", "features": {"char_count": 1}}
    assert assert_no_raw_text(row) == []


def test_assert_no_raw_text_flags_every_forbidden_field():
    row = {"text": "x", "body": "y", "narrative": "z"}
    violations = assert_no_raw_text(row)
    assert "forbidden-field:text" in violations
    assert "forbidden-field:body" in violations
    assert "forbidden-field:narrative" in violations
    assert len(violations) == 3
