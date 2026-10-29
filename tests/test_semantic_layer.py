"""Unit tests for tools/semantic_layer.py — the query-indexed semantic layer.

These import the module directly under its fully-qualified package path
(tools.semantic_layer) — that is the key mutmut uses to match its trampoline
hits to mutants. Importing bare (as semantic_layer) leaves every mutant
unreached.

Every public function is covered with postcondition-derived assertions (not
mirrored from the implementation). CLI commands are tested via their Python
entry-points (cmd_* functions + main(argv)), not through subprocess, so mutmut
can kill mutants in the module.

# §4.1 exception: test files may exceed 500 lines when organized by fixture
# grouping (fixture-grouping exception, see .craftsmanship.conf). This file is organized
# by the 15 public API entry points of semantic_layer.py (load, save, validate,
# find, match, upsert, apply_feedback, stale_entries, render, cmd_*, main).
# Each section is a fixture group; splitting into separate files would replicate
# the _valid_entry helper and _FakeArgs class into every shard, increasing
# coupling, not reducing it.  Rationale: test_engineer.md §domain-context, bullet 1.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import tools.semantic_layer as sl


# ── constants ────────────────────────────────────────────────────────────────

def test_schema_version_is_1():
    assert sl.SCHEMA_VERSION == 1


def test_intents_contains_expected_values():
    assert sl.INTENTS == {"ingest", "verify", "compare", "monitor"}


def test_statuses_contains_expected_values():
    assert sl.STATUSES == {"fresh", "stale", "superseded"}


def test_entry_required_contains_all_required_fields():
    required = set(sl.ENTRY_REQUIRED)
    for field in ("query", "query_id", "intent", "domain", "status", "summary", "facts"):
        assert field in required


# ── load ─────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  absent file -> {"version": SCHEMA_VERSION, "entries": []}
#   (ii) existing file -> parsed data with version and entries defaulted if missing

def test_load_absent_file_returns_empty_doc(tmp_path: Path):
    doc = sl.load(tmp_path / "nope.yaml")
    assert doc == {"version": sl.SCHEMA_VERSION, "entries": []}


def test_load_existing_file_is_parsed(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    p.write_text("version: 1\nentries: []\n")
    doc = sl.load(p)
    assert doc["version"] == 1
    assert doc["entries"] == []


def test_load_defaults_version_when_absent(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    p.write_text("entries: []\n")
    doc = sl.load(p)
    assert doc["version"] == sl.SCHEMA_VERSION


def test_load_defaults_entries_when_absent(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    p.write_text("version: 1\n")
    doc = sl.load(p)
    assert doc["entries"] == []


def test_load_empty_file_returns_empty_doc(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    p.write_text("")
    doc = sl.load(p)
    assert doc["version"] == sl.SCHEMA_VERSION
    assert doc["entries"] == []


# ── save ─────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  saved file can be round-tripped via load
#   (ii) parent dirs are created if missing

def test_save_creates_parent_dirs(tmp_path: Path):
    p = tmp_path / "deep" / "dir" / "sl.yaml"
    sl.save(p, {"version": 1, "entries": []})
    assert p.exists()


def test_save_round_trips_via_load(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [{"query_id": "q1", "query": "test"}]}
    sl.save(p, data)
    loaded = sl.load(p)
    assert loaded["entries"][0]["query_id"] == "q1"


# ── validate_entry ────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   all required fields present + valid -> []
#   (ii)  missing required field -> error mentioning field name
#   (iii) invalid intent -> error mentioning "intent"
#   (iv)  invalid status -> error mentioning "status"
#   (v)   facts[i] not a dict -> error mentioning index
#   (vi)  facts[i] missing claim -> error
#   (vii) facts[i] missing source -> error

def _valid_entry(**overrides):
    base = {
        "query": "What is X?",
        "query_id": "q-001",
        "intent": "ingest",
        "domain": "research",
        "status": "fresh",
        "summary": "Summary of X.",
        "facts": [{"claim": "X is Y", "source": "https://example.com/page"}],
    }
    base.update(overrides)
    return base


def test_validate_entry_valid_returns_empty_list():
    assert sl.validate_entry(_valid_entry()) == []


def test_validate_entry_missing_query():
    entry = _valid_entry()
    del entry["query"]
    errors = sl.validate_entry(entry)
    assert any("query" in e for e in errors)


def test_validate_entry_missing_query_id():
    entry = _valid_entry()
    del entry["query_id"]
    errors = sl.validate_entry(entry)
    assert any("query_id" in e for e in errors)


def test_validate_entry_missing_intent():
    entry = _valid_entry()
    del entry["intent"]
    errors = sl.validate_entry(entry)
    assert any("intent" in e for e in errors)


def test_validate_entry_missing_domain():
    entry = _valid_entry()
    del entry["domain"]
    errors = sl.validate_entry(entry)
    assert any("domain" in e for e in errors)


def test_validate_entry_missing_status():
    entry = _valid_entry()
    del entry["status"]
    errors = sl.validate_entry(entry)
    assert any("status" in e for e in errors)


def test_validate_entry_missing_summary():
    entry = _valid_entry()
    del entry["summary"]
    errors = sl.validate_entry(entry)
    assert any("summary" in e for e in errors)


def test_validate_entry_missing_facts():
    entry = _valid_entry()
    del entry["facts"]
    errors = sl.validate_entry(entry)
    assert any("facts" in e for e in errors)


def test_validate_entry_invalid_intent():
    errors = sl.validate_entry(_valid_entry(intent="bad_intent"))
    assert any("intent" in e for e in errors)


def test_validate_entry_invalid_status():
    errors = sl.validate_entry(_valid_entry(status="unknown"))
    assert any("status" in e for e in errors)


def test_validate_entry_fact_not_dict():
    entry = _valid_entry(facts=["not a dict"])
    errors = sl.validate_entry(entry)
    assert any("facts[0]" in e and "mapping" in e for e in errors)


def test_validate_entry_fact_missing_claim():
    entry = _valid_entry(facts=[{"source": "https://x.com"}])
    errors = sl.validate_entry(entry)
    assert any("claim" in e for e in errors)


def test_validate_entry_fact_missing_source():
    entry = _valid_entry(facts=[{"claim": "X is Y"}])
    errors = sl.validate_entry(entry)
    assert any("source" in e for e in errors)


def test_validate_entry_continues_past_non_dict_fact():
    # A non-dict fact at index 0 must not prevent index 1 from being checked
    entry = _valid_entry(facts=["bad", {"claim": "X"}])
    errors = sl.validate_entry(entry)
    assert any("facts[0]" in e for e in errors)
    assert any("facts[1]" in e for e in errors)


def test_validate_entry_valid_intent_ingest():
    assert sl.validate_entry(_valid_entry(intent="ingest")) == []


def test_validate_entry_valid_intent_verify():
    assert sl.validate_entry(_valid_entry(intent="verify")) == []


def test_validate_entry_valid_intent_compare():
    assert sl.validate_entry(_valid_entry(intent="compare")) == []


def test_validate_entry_valid_intent_monitor():
    assert sl.validate_entry(_valid_entry(intent="monitor")) == []


def test_validate_entry_valid_status_fresh():
    assert sl.validate_entry(_valid_entry(status="fresh")) == []


def test_validate_entry_valid_status_stale():
    assert sl.validate_entry(_valid_entry(status="stale")) == []


def test_validate_entry_valid_status_superseded():
    assert sl.validate_entry(_valid_entry(status="superseded")) == []


# ── validate_file ─────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  valid file with no entries -> []
#   (ii) duplicate query_id -> error
#   (iii) entry-level errors are prefixed with [query_id]

def test_validate_file_empty_entries_returns_empty():
    assert sl.validate_file({"version": 1, "entries": []}) == []


def test_validate_file_duplicate_query_id_flagged():
    e1 = _valid_entry(query_id="dup")
    e2 = _valid_entry(query_id="dup")
    errors = sl.validate_file({"version": 1, "entries": [e1, e2]})
    assert any("duplicate query_id" in e and "dup" in e for e in errors)


def test_validate_file_entry_errors_prefixed_with_query_id():
    entry = _valid_entry(query_id="test-id")
    del entry["summary"]
    errors = sl.validate_file({"version": 1, "entries": [entry]})
    assert any("[test-id]" in e for e in errors)


def test_validate_file_valid_entry_produces_no_errors():
    errors = sl.validate_file({"version": 1, "entries": [_valid_entry()]})
    assert errors == []


# ── find ─────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  matching query_id -> entry dict
#   (ii) absent query_id -> None

def test_find_returns_entry_when_present():
    e = _valid_entry(query_id="find-me")
    data = {"entries": [e]}
    result = sl.find(data, "find-me")
    assert result is e


def test_find_returns_none_when_absent():
    data = {"entries": [_valid_entry(query_id="other")]}
    assert sl.find(data, "not-here") is None


def test_find_returns_none_on_empty_entries():
    assert sl.find({"entries": []}, "anything") is None


# ── match ─────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  case-insensitive substring match over query, query_id, aliases
#   (ii) no match -> []
#   (iii) multiple matches -> all returned

def test_match_finds_by_query_case_insensitive():
    e = _valid_entry(query="What is Python?", query_id="q1")
    data = {"entries": [e]}
    assert len(sl.match(data, "python")) == 1


def test_match_finds_by_query_id():
    e = _valid_entry(query_id="q-exact-001")
    data = {"entries": [e]}
    assert len(sl.match(data, "q-exact-001")) == 1


def test_match_finds_by_alias():
    e = _valid_entry(query_id="q1")
    e["aliases"] = ["py-alias"]
    data = {"entries": [e]}
    assert len(sl.match(data, "py-alias")) == 1


def test_match_no_match_returns_empty():
    data = {"entries": [_valid_entry(query="Something else", query_id="q1")]}
    assert sl.match(data, "zzznomatch") == []


def test_match_returns_multiple_hits():
    e1 = _valid_entry(query="What is Python?", query_id="q1")
    e2 = _valid_entry(query="Python tricks", query_id="q2")
    data = {"entries": [e1, e2]}
    hits = sl.match(data, "python")
    assert len(hits) == 2


def test_match_case_insensitive_uppercase_needle():
    e = _valid_entry(query="lowercase query", query_id="q1")
    data = {"entries": [e]}
    assert len(sl.match(data, "LOWERCASE")) == 1


# ── upsert ────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   new entry -> "created", appended to data["entries"]
#   (ii)  existing entry -> "updated", existing entry mutated in place
#   (iii) created date preserved on update
#   (iv)  updated date set on both create and update

def test_upsert_new_entry_returns_created():
    data = {"entries": []}
    action = sl.upsert(data, _valid_entry(query_id="new-q"))
    assert action == "created"


def test_upsert_new_entry_appended():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="new-q"))
    assert len(data["entries"]) == 1
    assert data["entries"][0]["query_id"] == "new-q"


def test_upsert_existing_entry_returns_updated():
    e = _valid_entry(query_id="existing")
    data = {"entries": [e]}
    action = sl.upsert(data, _valid_entry(query_id="existing", summary="new summary"))
    assert action == "updated"


def test_upsert_preserves_created_date_on_update():
    e = _valid_entry(query_id="existing")
    e["created"] = "2020-01-01"
    data = {"entries": [e]}
    sl.upsert(data, _valid_entry(query_id="existing"))
    assert data["entries"][0]["created"] == "2020-01-01"


def test_upsert_updated_field_is_set():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="q"))
    assert "updated" in data["entries"][0]


def test_upsert_no_duplicate_on_update():
    e = _valid_entry(query_id="existing")
    data = {"entries": [e]}
    sl.upsert(data, _valid_entry(query_id="existing"))
    assert len(data["entries"]) == 1


# ── apply_feedback ────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   "outcome" in fb -> entry["outcome"] = fb["outcome"]
#   (ii)  "gaps" in fb -> entry["gaps"] extended
#   (iii) fb["status"] present -> entry["status"] updated
#   (iv)  updated date is set

def test_apply_feedback_sets_outcome():
    entry = _valid_entry()
    sl.apply_feedback(entry, {"outcome": "success"})
    assert entry["outcome"] == "success"


def test_apply_feedback_extends_gaps():
    entry = _valid_entry()
    entry["gaps"] = [{"topic": "old", "status": "open"}]
    sl.apply_feedback(entry, {"gaps": [{"topic": "new", "status": "open"}]})
    assert len(entry["gaps"]) == 2


def test_apply_feedback_extends_gaps_when_none_existed():
    entry = _valid_entry()
    sl.apply_feedback(entry, {"gaps": [{"topic": "new", "status": "open"}]})
    assert len(entry["gaps"]) == 1


def test_apply_feedback_updates_status():
    entry = _valid_entry(status="fresh")
    sl.apply_feedback(entry, {"status": "stale"})
    assert entry["status"] == "stale"


def test_apply_feedback_sets_updated():
    entry = _valid_entry()
    sl.apply_feedback(entry, {})
    assert "updated" in entry


def test_apply_feedback_missing_outcome_does_not_set_it():
    entry = _valid_entry()
    sl.apply_feedback(entry, {"status": "stale"})
    assert "outcome" not in entry


def test_apply_feedback_missing_status_does_not_override():
    entry = _valid_entry(status="fresh")
    sl.apply_feedback(entry, {"outcome": "ok"})
    assert entry["status"] == "fresh"


# ── stale_entries ─────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   entry with status "stale" -> included
#   (ii)  entry with status "superseded" -> included
#   (iii) entry with revalidate_after <= today -> included
#   (iv)  entry with status "fresh" and future revalidate_after -> excluded
#   (v)   empty data -> []

def test_stale_entries_includes_stale_status():
    e = _valid_entry(status="stale")
    data = {"entries": [e]}
    assert len(sl.stale_entries(data)) == 1


def test_stale_entries_includes_superseded_status():
    e = _valid_entry(status="superseded")
    data = {"entries": [e]}
    assert len(sl.stale_entries(data)) == 1


def test_stale_entries_includes_past_revalidate_date():
    e = _valid_entry(status="fresh")
    e["freshness"] = {"revalidate_after": "2000-01-01"}
    data = {"entries": [e]}
    assert len(sl.stale_entries(data)) == 1


def test_stale_entries_excludes_fresh_with_future_revalidate():
    e = _valid_entry(status="fresh")
    e["freshness"] = {"revalidate_after": "2099-01-01"}
    data = {"entries": [e]}
    assert sl.stale_entries(data) == []


def test_stale_entries_empty_data_returns_empty():
    assert sl.stale_entries({"entries": []}) == []


def test_stale_entries_excludes_fresh_without_revalidate():
    data = {"entries": [_valid_entry(status="fresh")]}
    assert sl.stale_entries(data) == []


# ── render ────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   output contains query and query_id
#   (ii)  output contains status, intent, domain
#   (iii) output contains summary
#   (iv)  output contains each fact's claim and source
#   (v)   open gaps are rendered; closed gaps are NOT
#   (vi)  cortex pointer is rendered when present

def test_render_contains_query():
    e = _valid_entry(query="What is X?", query_id="q1")
    assert "What is X?" in sl.render(e)


def test_render_contains_query_id():
    e = _valid_entry(query_id="q-render-001")
    assert "q-render-001" in sl.render(e)


def test_render_contains_status():
    e = _valid_entry(status="fresh")
    assert "fresh" in sl.render(e)


def test_render_contains_summary():
    e = _valid_entry(summary="A key finding.")
    assert "A key finding." in sl.render(e)


def test_render_contains_fact_claim():
    e = _valid_entry(facts=[{"claim": "the claim", "source": "https://x.com"}])
    assert "the claim" in sl.render(e)


def test_render_contains_fact_source():
    e = _valid_entry(facts=[{"claim": "c", "source": "https://example.com/src"}])
    assert "https://example.com/src" in sl.render(e)


def test_render_includes_open_gaps():
    e = _valid_entry()
    e["gaps"] = [{"topic": "gap topic", "status": "open"}]
    assert "gap topic" in sl.render(e)


def test_render_excludes_closed_gaps():
    e = _valid_entry()
    e["gaps"] = [{"topic": "closed gap", "status": "closed"}]
    assert "closed gap" not in sl.render(e)


def test_render_includes_cortex_pointer():
    e = _valid_entry()
    e["pointers"] = {"cortex_memories": ["mem-123"]}
    assert "mem-123" in sl.render(e)


def test_render_missing_query_uses_fallback():
    e = _valid_entry()
    del e["query"]
    result = sl.render(e)
    assert "(no query)" in result


# ── cmd_init ──────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)  new path -> file created, exit 0
#   (ii) existing path -> file unchanged, exit 0

def test_cmd_init_creates_file(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    code = sl.cmd_init(p, None)
    assert code == 0
    assert p.exists()


def test_cmd_init_creates_valid_empty_doc(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    doc = sl.load(p)
    assert doc["entries"] == []
    assert doc["version"] == sl.SCHEMA_VERSION


def test_cmd_init_existing_file_not_overwritten(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    p.write_text("version: 1\nentries:\n  - query_id: keep-me\n")
    sl.cmd_init(p, None)
    doc = sl.load(p)
    assert any(e.get("query_id") == "keep-me" for e in doc.get("entries", []))


def test_cmd_init_existing_file_returns_zero(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    p.write_text("version: 1\nentries: []\n")
    code = sl.cmd_init(p, None)
    assert code == 0


# ── cmd_query ─────────────────────────────────────────────────────────────────

class _FakeArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_cmd_query_no_hits_prints_message(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    code = sl.cmd_query(p, _FakeArgs(text="zzz", json=False))
    assert code == 0
    out = capsys.readouterr().out
    assert "no semantic-layer entry" in out


def test_cmd_query_json_flag_emits_json(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(query="Python test", query_id="q1")]}
    sl.save(p, data)
    code = sl.cmd_query(p, _FakeArgs(text="python", json=True))
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_cmd_query_renders_hits_as_text(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(query="Python test", query_id="q1")]}
    sl.save(p, data)
    code = sl.cmd_query(p, _FakeArgs(text="python", json=False))
    assert code == 0
    out = capsys.readouterr().out
    assert "q1" in out


# ── cmd_record ────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   valid entry on stdin -> saved and exit 0
#   (ii)  invalid entry -> error on stderr, exit 2

def test_cmd_record_valid_entry_saves_and_returns_zero(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    entry = _valid_entry(query_id="r-001")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        code = sl.cmd_record(p, None)
    assert code == 0
    doc = sl.load(p)
    assert sl.find(doc, "r-001") is not None


def test_cmd_record_invalid_entry_returns_two(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    bad = {"query_id": "bad"}  # missing many required fields
    with patch("sys.stdin", io.StringIO(json.dumps(bad))):
        code = sl.cmd_record(p, None)
    assert code == 2


def test_cmd_record_invalid_entry_writes_to_stderr(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    bad = {"query_id": "bad"}
    with patch("sys.stdin", io.StringIO(json.dumps(bad))):
        sl.cmd_record(p, None)
    err = capsys.readouterr().err
    assert "validation failed" in err


# ── cmd_feedback ──────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   existing query_id -> feedback applied, exit 0
#   (ii)  unknown query_id -> error on stderr, exit 2

def test_cmd_feedback_applies_to_existing_entry(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(query_id="fb-001")]}
    sl.save(p, data)
    fb = {"outcome": "verified", "status": "stale"}
    with patch("sys.stdin", io.StringIO(json.dumps(fb))):
        code = sl.cmd_feedback(p, _FakeArgs(query_id="fb-001"))
    assert code == 0
    doc = sl.load(p)
    entry = sl.find(doc, "fb-001")
    assert entry["outcome"] == "verified"
    assert entry["status"] == "stale"


def test_cmd_feedback_unknown_query_id_returns_two(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    with patch("sys.stdin", io.StringIO("{}")):
        code = sl.cmd_feedback(p, _FakeArgs(query_id="does-not-exist"))
    assert code == 2
    err = capsys.readouterr().err
    assert "no entry" in err


# ── cmd_revalidate ────────────────────────────────────────────────────────────

def test_cmd_revalidate_nothing_stale_prints_message(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(status="fresh")]}
    sl.save(p, data)
    code = sl.cmd_revalidate(p, _FakeArgs(json=False))
    assert code == 0
    assert "nothing to revalidate" in capsys.readouterr().out


def test_cmd_revalidate_stale_entry_rendered(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(status="stale", query_id="stale-q")]}
    sl.save(p, data)
    code = sl.cmd_revalidate(p, _FakeArgs(json=False))
    assert code == 0
    assert "stale-q" in capsys.readouterr().out


def test_cmd_revalidate_json_flag_emits_json(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(status="stale", query_id="stale-q")]}
    sl.save(p, data)
    code = sl.cmd_revalidate(p, _FakeArgs(json=True))
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


# ── cmd_validate ──────────────────────────────────────────────────────────────

def test_cmd_validate_valid_file_returns_zero(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry()]}
    sl.save(p, data)
    code = sl.cmd_validate(p, None)
    assert code == 0
    assert "valid" in capsys.readouterr().out


def test_cmd_validate_invalid_file_returns_two(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    bad_entry = {"query_id": "bad"}  # missing required fields
    data = {"version": 1, "entries": [bad_entry]}
    sl.save(p, data)
    code = sl.cmd_validate(p, None)
    assert code == 2
    assert "INVALID" in capsys.readouterr().err


# ── main ──────────────────────────────────────────────────────────────────────
# Postconditions:
#   (i)   unknown command -> parser error (non-zero)
#   (ii)  valid init -> exit 0
#   (iii) malformed YAML on record -> exit 1

def test_main_init_creates_file(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    code = sl.main(["--file", str(p), "init"])
    assert code == 0
    assert p.exists()


def test_main_query_no_hits(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    code = sl.main(["--file", str(p), "query", "nothing"])
    assert code == 0


def test_main_record_valid_entry(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    entry = _valid_entry(query_id="main-001")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        code = sl.main(["--file", str(p), "record"])
    assert code == 0


def test_main_record_malformed_json_returns_one(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    with patch("sys.stdin", io.StringIO("{bad json")):
        code = sl.main(["--file", str(p), "record"])
    assert code == 1


def test_main_validate_empty_file_returns_zero(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    code = sl.main(["--file", str(p), "validate"])
    assert code == 0


def test_main_revalidate_empty_file(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    code = sl.main(["--file", str(p), "revalidate"])
    assert code == 0


# ── targeted survivor-killing tests ──────────────────────────────────────────
# Each block addresses a specific class of surviving mutants.

# ── default-value mutations (data.get("entries", None/)) ─────────────────────
# Mutants replace [] default with None or nothing; tested by calling the
# function with a dict that has NO "entries" key — forces the default path.

def test_find_data_with_no_entries_key_returns_none():
    # exercises default-[] path for find()
    assert sl.find({}, "anything") is None


def test_match_data_with_no_entries_key_returns_empty():
    assert sl.match({}, "anything") == []


def test_validate_file_data_with_no_entries_key():
    # exercises default-[] path for validate_file()
    assert sl.validate_file({}) == []


def test_stale_entries_data_with_no_entries_key():
    assert sl.stale_entries({}) == []


# ── stale_entries: break vs continue ─────────────────────────────────────────
# _mutmut_18: 'continue' -> 'break'. With 'break', a stale entry stops the loop
# so subsequent fresh entries with past revalidate_after are NOT collected.
def test_stale_entries_collects_all_stale_not_just_first():
    # Two stale entries: both must be returned (break would stop after first)
    e1 = _valid_entry(status="stale", query_id="s1")
    e2 = _valid_entry(status="stale", query_id="s2")
    e3 = _valid_entry(status="fresh", query_id="s3")
    e3["freshness"] = {"revalidate_after": "2000-01-01"}
    data = {"entries": [e1, e3, e2]}  # interleave: stale, past-revalidate, stale
    result = sl.stale_entries(data)
    ids = {e["query_id"] for e in result}
    assert ids == {"s1", "s2", "s3"}  # all three must appear


def test_stale_entries_continues_past_first_stale():
    # After a stale entry, a fresh but overdue entry must still be collected
    e_stale = _valid_entry(status="stale", query_id="stale-first")
    e_overdue = _valid_entry(status="fresh", query_id="overdue")
    e_overdue["freshness"] = {"revalidate_after": "2000-01-01"}
    data = {"entries": [e_stale, e_overdue]}
    result = sl.stale_entries(data)
    ids = {e["query_id"] for e in result}
    assert "overdue" in ids


# ── stale_entries: < vs <= on revalidate_after ──────────────────────────────
# _mutmut_29: 'str(rev) <= now' -> 'str(rev) < now'. The boundary: when
# revalidate_after == today, <= includes it (overdue), < excludes it.
def test_stale_entries_boundary_today_is_overdue():
    # An entry whose revalidate_after is exactly today() must be included
    e = _valid_entry(status="fresh")
    e["freshness"] = {"revalidate_after": sl.today()}  # exactly today
    data = {"entries": [e]}
    assert len(sl.stale_entries(data)) == 1


# ── stale_entries: out.append(None) vs out.append(entry) ────────────────────
# _mutmut_30: appending None instead of the entry. Check the returned item
# is the actual entry object, not None.
def test_stale_entries_returns_entry_not_none():
    e = _valid_entry(status="stale", query_id="check-me")
    data = {"entries": [e]}
    result = sl.stale_entries(data)
    assert len(result) == 1
    assert result[0]["query_id"] == "check-me"
    assert result[0] is not None


# ── render: intent/domain fields ─────────────────────────────────────────────
# _mutmut_17,18,19: entry.get('intent') replaced with entry.get(None/'XXintentXX'/'INTENT').
# Check the actual intent value appears in the rendered string.
def test_render_contains_intent_value():
    e = _valid_entry(intent="verify")
    result = sl.render(e)
    assert "verify" in result


def test_render_contains_domain_value():
    e = _valid_entry(domain="ml-research")
    result = sl.render(e)
    assert "ml-research" in result


def test_render_fallback_no_query_shows_placeholder():
    # _mutmut_8: '(no query)' -> 'XX(no query)XX'
    e = _valid_entry()
    del e["query"]
    result = sl.render(e)
    assert "(no query)" in result
    assert "XX" not in result


# ── validate_file: query_id fallback ─────────────────────────────────────────
# _mutmut_11: entry.get("query_id", None) — need entry without query_id to
# exercise the fallback path. With None as default, duplicate detection
# would see two entries with None query_id as duplicates (wrong).
def test_validate_file_entry_without_query_id_uses_fallback():
    entry_no_id = {"query": "q", "status": "fresh"}  # no query_id
    data = {"entries": [entry_no_id]}
    # Should NOT crash; errors may contain field violations but no TypeError
    errors = sl.validate_file(data)
    assert isinstance(errors, list)


# _mutmut_16,17: '<no-id>' fallback replaced with 'XX<no-id>XX' or '<NO-ID>'
# Check duplicate detection uses the exact fallback '<no-id>' — two entries
# without query_id should both map to '<no-id>' and trigger duplicate detection.
def test_validate_file_two_entries_without_query_id_triggers_duplicate():
    e1 = {"query": "q1", "status": "fresh"}  # no query_id -> falls back to "<no-id>"
    e2 = {"query": "q2", "status": "fresh"}  # same fallback
    data = {"entries": [e1, e2]}
    errors = sl.validate_file(data)
    # Both map to "<no-id>", second triggers duplicate error
    assert any("duplicate" in err for err in errors)


# ── upsert: "created" key correctness ────────────────────────────────────────
# _mutmut_12: setdefault(None, ...) vs setdefault("created", ...)
# _mutmut_13: setdefault("created", None) vs setdefault("created", today())
# _mutmut_15: setdefault("created", ) — no default value
# _mutmut_16: setdefault("XXcreatedXX", ...)

def test_upsert_new_entry_has_created_key():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="new"))
    assert "created" in data["entries"][0]


def test_upsert_new_entry_created_is_not_none():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="new"))
    assert data["entries"][0]["created"] is not None


def test_upsert_new_entry_created_is_date_string():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="new"))
    created = data["entries"][0]["created"]
    # Date strings are YYYY-MM-DD format (10 chars)
    assert isinstance(created, str) and len(created) == 10


# _mutmut_24,25: entry["XXcreatedXX"] or entry["CREATED"] instead of entry["created"]
# on the update path — the entry does NOT get the correct "created" key.
def test_upsert_update_entry_has_created_key():
    existing = _valid_entry(query_id="existing")
    existing["created"] = "2020-01-01"
    data = {"entries": [existing]}
    sl.upsert(data, _valid_entry(query_id="existing"))
    assert "created" in data["entries"][0]


# _mutmut_27: existing.get("created", None) vs existing.get("created", today())
# When existing entry has no "created" key, the fallback should be today(), not None.
def test_upsert_update_missing_created_falls_back_to_today():
    existing = _valid_entry(query_id="existing")
    # No "created" key
    data = {"entries": [existing]}
    sl.upsert(data, _valid_entry(query_id="existing"))
    assert data["entries"][0].get("created") is not None


# _mutmut_1: entry["updated"] = None instead of today()
def test_upsert_sets_updated_to_date_string():
    data = {"entries": []}
    sl.upsert(data, _valid_entry(query_id="q"))
    updated = data["entries"][0]["updated"]
    assert isinstance(updated, str) and len(updated) == 10


# ── apply_feedback: updated = None ───────────────────────────────────────────
# _mutmut_31: entry["updated"] = None
def test_apply_feedback_updated_is_date_string():
    entry = _valid_entry()
    sl.apply_feedback(entry, {})
    assert isinstance(entry.get("updated"), str)
    assert len(entry["updated"]) == 10


# ── save: yaml.safe_dump keyword arguments ───────────────────────────────────
# _mutmut_9: sort_keys=None (truthy in yaml, means sort keys — changes key order)
# _mutmut_10: allow_unicode=None
# _mutmut_11: width=None
# Test: key order preservation (sort_keys=False means original order maintained).
def test_save_preserves_key_order(tmp_path: Path):
    # If sort_keys=False, 'entries' before 'version' is preserved
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": []}
    sl.save(p, data)
    text = p.read_text()
    # sort_keys=False: 'version' should appear before 'entries' (dict insertion order)
    v_pos = text.find("version:")
    e_pos = text.find("entries:")
    assert v_pos < e_pos  # version key comes first per insertion order


def test_save_allows_unicode(tmp_path: Path):
    # allow_unicode=True means unicode chars are NOT escaped as \uXXXX
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [{"summary": "café résumé"}]}
    sl.save(p, data)
    text = p.read_text()
    assert "café" in text  # not escaped as é etc.


# ── cmd_init: correct schema in saved file ───────────────────────────────────
# _mutmut_7,8: "XXversionXX"/"VERSION" instead of "version"
# _mutmut_9: "XXentriesXX" instead of "entries"
def test_cmd_init_saved_file_has_version_key(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    doc = sl.load(p)
    assert "version" in doc


def test_cmd_init_saved_file_has_entries_key(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    doc = sl.load(p)
    assert "entries" in doc


# _mutmut_1: print(None) instead of print(f"already exists: {path}")
def test_cmd_init_existing_prints_already_exists(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    p.write_text("version: 1\nentries: []\n")
    sl.cmd_init(p, None)
    out = capsys.readouterr().out
    assert "already exists" in out


# _mutmut_4: save(path, None) — the file would be written with None as YAML
def test_cmd_init_file_content_is_valid_yaml(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    import yaml
    doc = yaml.safe_load(p.read_text())
    assert isinstance(doc, dict)


# ── match: haystack construction ─────────────────────────────────────────────
# Many match mutants replace "query"/"query_id"/"aliases" keys with None/XXX.
# Tests already cover finding by query, query_id, and aliases. But let me add
# tests that check the specific key names being used:

def test_match_uses_query_key_not_other_key():
    # Only "query" field contains "findme"; query_id and aliases don't
    e = {"query": "findme", "query_id": "q1", "aliases": []}
    data = {"entries": [e]}
    assert len(sl.match(data, "findme")) == 1


def test_match_uses_query_id_key_not_other_key():
    e = {"query": "other", "query_id": "target-id-001", "aliases": []}
    data = {"entries": [e]}
    assert len(sl.match(data, "target-id-001")) == 1


def test_match_uses_aliases_key():
    e = {"query": "q", "query_id": "q1", "aliases": ["unique-alias-xyz"]}
    data = {"entries": [e]}
    assert len(sl.match(data, "unique-alias-xyz")) == 1


def test_match_handles_entry_with_no_aliases_key():
    # aliases field absent; must not crash
    e = {"query": "q", "query_id": "q1"}
    data = {"entries": [e]}
    assert isinstance(sl.match(data, "q"), list)


# ── render: additional field assertions ──────────────────────────────────────
# Render already tested, but add exact-value checks for the mutated fields.
def test_render_shows_actual_intent_not_none():
    e = _valid_entry(intent="compare")
    result = sl.render(e)
    assert "intent=compare" in result


def test_render_shows_actual_domain_not_none():
    e = _valid_entry(domain="astrophysics")
    result = sl.render(e)
    assert "domain=astrophysics" in result


# ── save: yaml parameters — width=101 vs 100, width=None ────────────────────
# _mutmut_9: sort_keys=None (truthy) — key order changes
# _mutmut_11: width=None — default YAML width (different line wrapping)
# _mutmut_15: width= trailing comma (width omitted = default)
# _mutmut_18: width=101
# These manifest as line-wrapping differences: width=100 wraps at 100 chars.
def test_save_preserves_insertion_key_order(tmp_path: Path):
    # sort_keys=False must preserve insertion order; sort_keys=None (truthy) sorts them.
    # Use keys that differ in alphabetical vs insertion order.
    p = tmp_path / "sl.yaml"
    # "zebra" before "alpha" — if sort_keys=False, YAML preserves this order
    data = {"zebra": 1, "alpha": 2}
    sl.save(p, data)
    text = p.read_text()
    # "zebra:" must appear BEFORE "alpha:" in the file
    assert text.index("zebra:") < text.index("alpha:")


def test_save_long_sentence_wraps_at_100_not_80(tmp_path: Path):
    # width=100 wraps at 100 chars; width=None uses YAML default (~80).
    # A long sentence that is > 80 but < 100 total width should NOT be folded at width=100
    # but WOULD be folded at width=None (~80). Use "word " * N to trigger folding.
    p = tmp_path / "sl.yaml"
    # 20 words of "word " = 100 chars. At width=100 it wraps after the 100th char;
    # at width=None (~80) it wraps earlier. Both produce correct round-trips.
    # The distinguishing postcondition: width=100 keeps the first 100 chars on one line.
    long_val = "word " * 20  # 100 chars including trailing space
    data = {"sentence": long_val.strip()}
    sl.save(p, data)
    text = p.read_text()
    import yaml as _yaml
    loaded = _yaml.safe_load(text)
    assert loaded["sentence"] == long_val.strip()  # data round-trips
    # With width=100, the first line holds more words than with width=None.
    # Check the first line of the value is at least 95 chars (indicating width=100 not ~80).
    first_line = text.split("\n")[0]
    assert len(first_line) >= 95  # width=100 → first line is ~100 chars


# ── match: default empty string fallback for query ───────────────────────────
# _mutmut_12: entry.get("query", None) — with None default, an entry with
# no "query" field gives None; then 'needle in None.lower()' would crash.
# _mutmut_14: entry.get("query", ) — same crash risk.
# _mutmut_17: entry.get("query", "XXXX") — never matches needle "findme" via
# the default, but still works for entries WITH query. Not observable unless
# the query is absent.
# Test: match on an entry with no "query" key must not crash.
def test_match_entry_without_query_key_does_not_crash():
    e = {"query_id": "q1"}  # no "query" key
    data = {"entries": [e]}
    result = sl.match(data, "q1")  # should find via query_id
    assert len(result) == 1


# ── render: updated field ─────────────────────────────────────────────────────
# _mutmut_23: entry.get(None) instead of entry.get("updated")
def test_render_contains_updated_value():
    e = _valid_entry()
    e["updated"] = "2026-01-01"
    result = sl.render(e)
    assert "updated=2026-01-01" in result


# ── render: gap status field ──────────────────────────────────────────────────
# _mutmut_58: gap.get(None, 'open') instead of gap.get('status', 'open')
# An open gap should show its status; a gap with explicit status should show it.
def test_render_gap_shows_status():
    e = _valid_entry()
    e["gaps"] = [{"topic": "gap topic", "status": "open"}]
    result = sl.render(e)
    assert "(open)" in result


def test_render_gap_shows_non_open_status():
    e = _valid_entry()
    e["gaps"] = [{"topic": "gap topic", "status": "investigating"}]
    result = sl.render(e)
    assert "(investigating)" in result


# ── render: cortex pointer join separator ─────────────────────────────────────
# _mutmut_76: 'XX, XX'.join(...) instead of ', '.join(...)
def test_render_cortex_pointers_joined_with_comma_space():
    e = _valid_entry()
    e["pointers"] = {"cortex_memories": ["mem-1", "mem-2"]}
    result = sl.render(e)
    assert "mem-1, mem-2" in result
    assert "XX" not in result


# ── read_stdin_json: error message ───────────────────────────────────────────
# _mutmut_3,4,5,6: sys.exit(None), sys.exit("XX..."), sys.exit(lowercase), etc.
# The function calls sys.exit() which raises SystemExit. Test the message.
def test_read_stdin_json_empty_stdin_exits_with_message():
    with patch("sys.stdin", io.StringIO("")):
        with pytest.raises(SystemExit) as exc_info:
            sl.read_stdin_json()
    # exit message should contain "error:" — catches None/lowercase/XX mutations
    msg = str(exc_info.value.args[0]) if exc_info.value.args else ""
    assert "error:" in msg
    assert "XX" not in msg


# ── cmd_init: "entries" key case ─────────────────────────────────────────────
# _mutmut_10: "ENTRIES" instead of "entries". Check the loaded doc has lowercase.
def test_cmd_init_entries_key_is_lowercase(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    import yaml
    text = p.read_text()
    assert "entries:" in text
    assert "ENTRIES:" not in text


# _mutmut_11: print(None) instead of print(f"initialized: {path}")
def test_cmd_init_prints_initialized_with_path(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    out = capsys.readouterr().out
    assert "initialized" in out
    assert str(p) in out


# ── cmd_query: indented JSON output ──────────────────────────────────────────
# _mutmut_9: indent=None (compact), _mutmut_11: indent dropped
def test_cmd_query_json_output_is_indented(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(query="Python test", query_id="q1")]}
    sl.save(p, data)
    sl.cmd_query(p, _FakeArgs(text="python", json=True))
    out = capsys.readouterr().out
    # indent=2: a JSON array of objects — outer array items at 2 spaces,
    # inner keys at 4 spaces. Check "\n    \"" (4-space indent of nested key).
    assert '\n    "' in out  # 4-space indent for dict keys inside array


# ── cmd_record: validation error message ─────────────────────────────────────
# _mutmut_9: "XXvalidation failed" prefix
def test_cmd_record_validation_error_starts_with_validation_failed(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    bad = {"query_id": "bad"}
    with patch("sys.stdin", io.StringIO(json.dumps(bad))):
        sl.cmd_record(p, None)
    err = capsys.readouterr().err
    assert "validation failed:" in err
    assert "XX" not in err


# ── cmd_revalidate: indented JSON + no-stale message ─────────────────────────
# _mutmut_6,8: indent=None or omitted
def test_cmd_revalidate_json_output_is_indented(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    data = {"version": 1, "entries": [_valid_entry(status="stale", query_id="s1")]}
    sl.save(p, data)
    sl.cmd_revalidate(p, _FakeArgs(json=True))
    out = capsys.readouterr().out
    # indent=2: array of dicts — nested keys at 4 spaces
    assert '\n    "' in out


# ── cmd_validate: INVALID error message ──────────────────────────────────────
# _mutmut_9: "XXINVALID:\n  XX" instead of "INVALID:\n  "
def test_cmd_validate_invalid_message_starts_with_invalid(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    bad_entry = {"query_id": "bad"}
    data = {"version": 1, "entries": [bad_entry]}
    sl.save(p, data)
    sl.cmd_validate(p, None)
    err = capsys.readouterr().err
    assert "INVALID:" in err
    assert "XX" not in err


# ── main: malformed input error message ──────────────────────────────────────
# _mutmut_8: print(None, ...) instead of print(f"error: malformed input — {exc}", ...)
def test_main_malformed_yaml_error_message_on_stderr(tmp_path: Path, capsys):
    # Write a valid YAML file, then record will try to parse stdin as JSON
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    # Now trigger a YAMLError by writing bad YAML content to the file
    p.write_text("{ unclosed: [")
    code = sl.main(["--file", str(p), "validate"])
    assert code == 1
    err = capsys.readouterr().err
    assert "error:" in err or "malformed" in err


# ── validate_file: <no-id> fallback in error message ─────────────────────────
# _mutmut_11,13: None or no arg as fallback — None would appear as "None" in error
# _mutmut_16: "XX<no-id>XX" — would collide but differ
# _mutmut_17: "<NO-ID>" (uppercase) — different collision behavior
# Two entries without query_id key: both get fallback, de-dup fires, error message
# must contain "<no-id>" (lowercase, angle-bracketed) NOT "None" or "<NO-ID>"
def test_validate_file_two_entries_no_query_id_error_contains_no_id_lowercase():
    e1 = {"query": "A"}
    e2 = {"query": "B"}
    data = {"version": 1, "entries": [e1, e2]}
    errs = sl.validate_file(data)
    # The error string must contain exactly "<no-id>" (lowercase, angle-bracketed)
    assert any("<no-id>" in e for e in errs)
    assert not any("None" in e for e in errs)
    assert not any("<NO-ID>" in e for e in errs)
    # Explicitly reject the XX-wrapped mutant variant
    assert not any("XX<no-id>XX" in e for e in errs)


# ── match: entry with no query_id key uses empty-string default ───────────────
# _mutmut_19,21: None or no default — would crash `.lower()` call on None
# _mutmut_24: "XXXX" default — would never match "" or real text
def test_match_entry_without_query_id_key_does_not_crash():
    e = {"query": "some text", "query_id": "q-exists"}
    e2 = {"query": "another query"}  # no query_id key
    data = {"entries": [e, e2]}
    # match on the first entry; this exercises the query_id default for e2
    result = sl.match(data, "some text")
    assert len(result) == 1
    assert result[0]["query_id"] == "q-exists"


def test_match_entry_without_query_key_not_matched_via_default():
    # Entry with no "query" key: should NOT be found when needle is "xx"
    # because the default is "" (empty string), not "XXXX"
    e = {"query_id": "no-query-entry"}  # no "query" key
    data = {"entries": [e]}
    result = sl.match(data, "xx")
    # "xx" should NOT match via the empty-string default for query
    assert len(result) == 0


def test_match_entry_without_query_id_key_not_matched_via_default():
    # Entry with no "query_id" key: should NOT be found when needle is "xx"
    # because the default is "" (empty string), not "XXXX"
    e = {"query": "real query text"}  # no "query_id" key
    data = {"entries": [e]}
    result = sl.match(data, "xx")
    # "xx" should NOT match via the empty-string default for query_id
    assert len(result) == 0


# ── match: entry with no aliases key uses empty-list default ─────────────────
# _mutmut_28: aliases default=None (but `or []` handles that — same result)
# _mutmut_30: aliases default with no arg (same crash risk as None)
# These are actually equivalent: `entry.get("aliases", None) or []` == `entry.get("aliases", []) or []`
# because both produce [] when the key is absent. Document as equivalent.
# _mutmut_28,30: EQUIVALENT — `get(key, None) or []` and `get(key, []) or []`
# produce identical results when key is absent (None or [] both -> [] via `or`).


# ── render: gap with no "status" key uses "open" default ─────────────────────
# _mutmut_59: gap.get("status", None) — gap with no "status" key would show "None"
# _mutmut_61: gap.get("status", ) — no default, would crash
# _mutmut_64: "XXopenXX" default
# _mutmut_65: "OPEN" (uppercase) default
def test_render_gap_without_status_key_shows_open():
    e = _valid_entry()
    e["gaps"] = [{"topic": "missing status"}]  # no "status" key
    result = sl.render(e)
    assert "(open)" in result
    assert "(OPEN)" not in result
    assert "XX" not in result
    # Check the gap line specifically — not the full render (updated=None is expected)
    gap_lines = [ln for ln in result.splitlines() if "gap:" in ln]
    assert len(gap_lines) == 1
    assert "(open)" in gap_lines[0]
    assert "None" not in gap_lines[0]


# ── read_stdin_json: error message is case-sensitive ("JSON" uppercase) ───────
# _mutmut_5: "json" (lowercase) instead of "JSON"
def test_read_stdin_json_error_message_has_uppercase_JSON():
    with patch("sys.stdin", io.StringIO("")):
        with pytest.raises(SystemExit) as exc_info:
            sl.read_stdin_json()
    msg = str(exc_info.value.args[0]) if exc_info.value.args else ""
    # Contract: "JSON" uppercase is the standard user-facing term
    assert "JSON" in msg


# ── cmd_init: "version" key in saved YAML is exact string ─────────────────────
# _mutmut_7: "XXversionXX", _mutmut_8: "VERSION"
def test_cmd_init_version_key_is_exact_lowercase(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    import yaml as _yaml
    loaded = _yaml.safe_load(p.read_text())
    assert "version" in loaded
    assert "XXversionXX" not in loaded
    assert "VERSION" not in loaded


# ── cmd_query: multiple-hit separator is "\n\n" not "XX\n\nXX" ───────────────
# _mutmut_19: separator becomes "XX\n\nXX"
def test_cmd_query_text_hits_separated_by_double_newline(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    e1 = _valid_entry(query="Python basics", query_id="py1")
    e2 = _valid_entry(query="Python advanced", query_id="py2")
    data = {"version": 1, "entries": [e1, e2]}
    sl.save(p, data)
    sl.cmd_query(p, _FakeArgs(text="python", json=False))
    out = capsys.readouterr().out
    assert "\n\n" in out
    assert "XX" not in out


# ── cmd_record: success message contains action and query_id ─────────────────
# _mutmut_25: print(None)
def test_cmd_record_success_prints_action_and_query_id(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    entry = _valid_entry(query_id="myq1")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        rc = sl.cmd_record(p, None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "myq1" in out
    assert out.strip() != "None"


# ── cmd_feedback: success message contains query_id ──────────────────────────
# _mutmut_22: print(None)
def test_cmd_feedback_success_prints_feedback_applied(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    entry = _valid_entry(query_id="fbq1")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        sl.cmd_record(p, None)
    capsys.readouterr()  # flush record output
    feedback = {"corrected_domain": "science"}
    with patch("sys.stdin", io.StringIO(json.dumps(feedback))):
        rc = sl.cmd_feedback(p, _FakeArgs(query_id="fbq1"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "fbq1" in out
    assert out.strip() != "None"


# ── cmd_revalidate: plain text output messages ────────────────────────────────
# _mutmut_13: "(nothing to revalidate)" becomes "XX(nothing to revalidate)XX"
def test_cmd_revalidate_empty_message_is_exact(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    sl.cmd_revalidate(p, _FakeArgs(json=False))
    out = capsys.readouterr().out
    assert "(nothing to revalidate)" in out
    assert "XX" not in out


# _mutmut_16,17,18,19: "Entries needing revalidation:" mutated
# _mutmut_22: join separator becomes "XX\n\nXX"
def test_cmd_revalidate_text_output_has_header_and_entries(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    e1 = _valid_entry(status="stale", query_id="s1")
    e2 = _valid_entry(status="stale", query_id="s2")
    data = {"version": 1, "entries": [e1, e2]}
    sl.save(p, data)
    sl.cmd_revalidate(p, _FakeArgs(json=False))
    out = capsys.readouterr().out
    assert "Entries needing revalidation:" in out
    assert "XX" not in out
    # two entries separated by \n\n
    assert "\n\n" in out


# ── cmd_validate: success message is "valid" ─────────────────────────────────
# _mutmut_15: "XXvalidXX" instead of "valid"
def test_cmd_validate_success_prints_valid(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.cmd_init(p, None)
    rc = sl.cmd_validate(p, None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "valid" in out
    assert "XX" not in out


# ── build_parser: --file required=True  ──────────────────────────────────────
# _mutmut_6: required=None (falsy, so optional), _mutmut_9: required= omitted
# When --file is absent, parser should exit with an error.
def test_build_parser_file_argument_is_required():
    parser = sl.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["init"])  # missing --file
    assert exc_info.value.code != 0


# ── build_parser: --json flag is a boolean store_true ─────────────────────────
# _mutmut_36: action=None (makes --json require a string value, not boolean)
# _mutmut_38: action= omitted (same effect — not store_true)
# Kill via main() which parses through build_parser.
def test_main_query_json_flag_produces_valid_json(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    entry = _valid_entry(query="json test", query_id="jt1")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        sl.main(["--file", str(p), "record"])
    capsys.readouterr()  # flush
    # --json flag with no value: should be a boolean switch (store_true)
    code = sl.main(["--file", str(p), "query", "json test", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    # output must be parseable as JSON (not just a Python repr with True/False)
    data = json.loads(out)
    assert isinstance(data, list)


def test_main_revalidate_json_flag_works_as_boolean(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    e = _valid_entry(status="stale", query_id="sv1")
    data = {"version": 1, "entries": [e]}
    sl.save(p, data)
    # --json as store_true: no argument needed after the flag
    code = sl.main(["--file", str(p), "revalidate", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    parsed = json.loads(out)
    assert isinstance(parsed, list)


# ── build_parser: feedback and revalidate subcommand names ───────────────────
# _mutmut_49: sub.add_parser(None) for feedback — "feedback" subcommand vanishes
# Kill via main() calling "feedback"
def test_main_feedback_subcommand_is_accessible(tmp_path: Path, capsys):
    p = tmp_path / "sl.yaml"
    sl.main(["--file", str(p), "init"])
    entry = _valid_entry(query_id="fbtest")
    with patch("sys.stdin", io.StringIO(json.dumps(entry))):
        sl.main(["--file", str(p), "record"])
    capsys.readouterr()
    feedback = {"summary": "updated summary"}
    with patch("sys.stdin", io.StringIO(json.dumps(feedback))):
        code = sl.main(["--file", str(p), "feedback", "fbtest"])
    assert code == 0


# ── build_parser: subparsers required=True ───────────────────────────────────
# _mutmut_18: required=None (falsy → not required → no error on missing subcommand)
# _mutmut_20: required= dropped (same)
# _mutmut_23: required=False (explicit False)
# When no subcommand is given, parser must exit with a non-zero code.
def test_main_no_subcommand_exits_nonzero(tmp_path: Path):
    p = tmp_path / "sl.yaml"
    with pytest.raises(SystemExit) as exc_info:
        sl.main(["--file", str(p)])  # missing subcommand
    assert exc_info.value.code != 0


# ── build_parser: subparsers dest="cmd" ──────────────────────────────────────
# _mutmut_19: dest= dropped
# _mutmut_21: dest="XXcmdXX"
# _mutmut_22: dest="CMD"
# These affect args.cmd but main() routes via args.func — they are equivalent
# because main() does not use args.cmd directly. Document as equivalent.
# EQUIVALENT: build_parser__mutmut_19, 21, 22
# Rationale: main() dispatches via `args.func(Path(args.file), args)` —
# the `dest="cmd"` value is not used in any postcondition; it only sets args.cmd
# which no tested code path reads. Runtime behavior is identical.

# build_parser_mutmut_2,3,4: prog name mutations — documentation only; equivalent.
# build_parser_mutmut_7,10,14,15: --file help text — documentation only; equivalent.
# build_parser_mutmut_18,20,23: already killed above via no-subcommand test.
# EQUIVALENT (prog/help text/dest): build_parser__mutmut_2, 3, 4, 7, 10, 14, 15, 19, 21, 22
# Rationale: argparse prog name and help text are documentation strings only.
