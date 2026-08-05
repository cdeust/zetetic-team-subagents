"""Unit tests for the pure-function core of tools.goa.ci_no_raw_corpus_text and
tools.goa.fixture_freeze_gate. Full git-integration behavior (git ls-files,
git show across refs) is covered by the shell regression suites at
tools/tests/goa-no-raw-text-gate/ and tools/tests/goa-fixture-freeze-gate/ —
these tests exercise the deterministic logic directly, without spawning git.
"""
from __future__ import annotations

import json

from tools.goa.ci_no_raw_corpus_text import (
    FIXTURE_JSON_RE,
    READONLY_REFERENCE_RE,
    _is_marked_synthetic,
    check_fixture_schema,
    find_suspicious_raw_dump_files,
)
from tools.goa.fixture_freeze_gate import diff_rows


def test_fixture_json_re_matches_versioned_fixture_names():
    assert FIXTURE_JSON_RE.search("tools/goa/fixtures/external_testbase_v1.json")
    assert FIXTURE_JSON_RE.search("external_testbase_v12.json")
    assert not FIXTURE_JSON_RE.search("external_testbase.json")


def test_readonly_reference_re_matches_case_insensitively():
    assert READONLY_REFERENCE_RE.search("data/swebench_readonly_reference.jsonl")
    assert READONLY_REFERENCE_RE.search("data/SWEBENCH_READONLY_REFERENCE.jsonl")


def test_is_marked_synthetic_recognizes_both_marker_forms():
    assert _is_marked_synthetic("tests/fixtures/goa/Posts.synthetic.xml")
    assert _is_marked_synthetic("tests/fixtures/goa/synthetic/Posts.xml")
    assert not _is_marked_synthetic("data/dumps/Posts.xml")


def test_check_fixture_schema_flags_forbidden_field(tmp_path):
    fixture_path = tmp_path / "external_testbase_v1.json"
    fixture_path.write_text(
        json.dumps({"rows": [{"case_id": "a1", "source_id": "s1", "license": "L", "text": "leaked raw text"}]}),
        encoding="utf-8",
    )
    violations = check_fixture_schema(tmp_path, ["external_testbase_v1.json"])
    assert any("forbidden-field:text" in v for v in violations)


def test_check_fixture_schema_flags_missing_license(tmp_path):
    fixture_path = tmp_path / "external_testbase_v1.json"
    fixture_path.write_text(
        json.dumps({"rows": [{"case_id": "a1", "source_id": "s1", "features": {}}]}), encoding="utf-8"
    )
    violations = check_fixture_schema(tmp_path, ["external_testbase_v1.json"])
    assert any("missing-source_id-or-license" in v for v in violations)


def test_check_fixture_schema_clean_row_is_no_violation(tmp_path):
    fixture_path = tmp_path / "external_testbase_v1.json"
    fixture_path.write_text(
        json.dumps({"rows": [{"case_id": "a1", "source_id": "s1", "license": "L", "features": {}}]}),
        encoding="utf-8",
    )
    assert check_fixture_schema(tmp_path, ["external_testbase_v1.json"]) == []


def test_check_fixture_schema_ignores_non_fixture_files(tmp_path):
    (tmp_path / "notes.json").write_text(json.dumps({"rows": [{"text": "irrelevant"}]}), encoding="utf-8")
    assert check_fixture_schema(tmp_path, ["notes.json"]) == []


def test_find_suspicious_raw_dump_files_flags_unmarked_dump(tmp_path):
    (tmp_path / "Posts.xml").write_text("<posts/>", encoding="utf-8")
    suspicious = find_suspicious_raw_dump_files(tmp_path, ["Posts.xml"])
    assert len(suspicious) == 1


def test_find_suspicious_raw_dump_files_allows_tiny_marked_synthetic(tmp_path):
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "synthetic" / "Posts.xml").write_text("<posts/>", encoding="utf-8")
    suspicious = find_suspicious_raw_dump_files(tmp_path, ["synthetic/Posts.xml"])
    assert suspicious == []


def test_find_suspicious_raw_dump_files_flags_oversized_marked_synthetic(tmp_path):
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "synthetic" / "Posts.xml").write_text("x" * 9000, encoding="utf-8")
    suspicious = find_suspicious_raw_dump_files(tmp_path, ["synthetic/Posts.xml"])
    assert len(suspicious) == 1
    assert "exceeds" in suspicious[0]


def test_find_suspicious_raw_dump_files_ignores_unrelated_files(tmp_path):
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    assert find_suspicious_raw_dump_files(tmp_path, ["README.md"]) == []


def test_diff_rows_flags_removed_row():
    base_rows = [{"case_id": "a1", "label": "x"}]
    head_rows = []
    violations = diff_rows(base_rows, head_rows)
    assert "a1: removed from fixture (append-only violation)" in violations


def test_diff_rows_flags_modified_row():
    base_rows = [{"case_id": "a1", "label": "x"}]
    head_rows = [{"case_id": "a1", "label": "y"}]
    violations = diff_rows(base_rows, head_rows)
    assert "a1: existing row modified (append-only violation)" in violations


def test_diff_rows_allows_pure_addition():
    base_rows = [{"case_id": "a1", "label": "x"}]
    head_rows = [{"case_id": "a1", "label": "x"}, {"case_id": "a2", "label": "y"}]
    assert diff_rows(base_rows, head_rows) == []
