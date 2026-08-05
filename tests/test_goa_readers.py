"""Unit tests for tools.goa.se_dump_reader and tools.goa.ntsb_reader.

Both readers are exercised against tiny, FORMAT-ONLY synthetic fixtures under
tests/fixtures/goa/synthetic/ — invented content mimicking the real dump
STRUCTURE, never real corpus text (task constraint: no raw corpus text
anywhere in this repo, see tools/goa/ci_no_raw_corpus_text.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.goa.ntsb_reader import NTSB_LICENSE, read_occurrences
from tools.goa.se_dump_reader import parse_tags, read_posts

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "goa" / "synthetic"


def test_parse_tags_splits_angle_bracket_list():
    assert parse_tags("<causality><experiment-design>") == ("causality", "experiment-design")


def test_parse_tags_empty_returns_empty_tuple():
    assert parse_tags(None) == ()
    assert parse_tags("") == ()


def test_read_posts_keeps_only_questions_matching_allowlist():
    records, drops = read_posts(
        FIXTURES / "Posts.xml",
        site="stats.stackexchange.com",
        license_str="CC BY-SA 4.0",
        tag_allowlist=("causality", "experiment-design"),
    )
    assert [r.source_id for r in records] == ["1"]
    assert drops["not-a-question"] == 1  # the PostTypeId=2 row
    assert drops["tag-not-in-allowlist"] == 2  # rows 3 (unrelated-tag) and 4 (observational-study)
    assert records[0].corpus == "stackexchange"
    assert records[0].site_or_dataset == "stats.stackexchange.com"
    assert records[0].score == 12


def test_read_posts_without_allowlist_returns_every_question():
    records, drops = read_posts(FIXTURES / "Posts.xml", site="s", license_str="l", tag_allowlist=())
    assert len(records) == 3  # rows 1, 3, 4 are PostTypeId=1
    assert "tag-not-in-allowlist" not in drops


def test_read_occurrences_csv_drops_rows_with_missing_text_field(tmp_path):
    records, drops = read_occurrences(
        FIXTURES / "ntsb_occurrences.synthetic.csv", text_field="narrative", id_field="occurrence_id"
    )
    assert [r.source_id for r in records] == ["occ-1", "occ-3"]  # occ-3 has a narrative, just no probable_cause
    assert drops["missing-field:narrative"] == 1  # occ-2 has empty narrative
    assert records[0].license == NTSB_LICENSE


def test_read_occurrences_csv_alternate_text_field():
    records, drops = read_occurrences(
        FIXTURES / "ntsb_occurrences.synthetic.csv", text_field="probable_cause", id_field="occurrence_id"
    )
    assert {r.source_id for r in records} == {"occ-1", "occ-2"}
    assert drops["missing-field:probable_cause"] == 1  # occ-3 has empty probable_cause


def test_read_occurrences_jsonl():
    records, drops = read_occurrences(
        FIXTURES / "ntsb_occurrences.synthetic.jsonl", text_field="narrative", id_field="occurrence_id"
    )
    assert len(records) == 2


def test_read_occurrences_rejects_unknown_extension(tmp_path):
    bad_path = tmp_path / "export.txt"
    bad_path.write_text("irrelevant", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported NTSB export extension"):
        read_occurrences(bad_path, text_field="narrative")
