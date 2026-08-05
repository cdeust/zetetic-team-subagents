"""Unit tests for tools.goa.concordance_gate — exact-agreement admission +
3rd-pass 2-of-3 adjudication, per EXTERNAL-TESTBASE.md §3 step 3."""
from __future__ import annotations

import json

import pytest

from tools.goa.concordance_gate import adjudicate_third_pass, load_labels, split_agreement


def _row(case_id: str, label: str) -> dict:
    return {"case_id": case_id, "label": label, "confidence": 0.9, "rationale": "r"}


def _write(tmp_path, name: str, rows: list[dict]):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_load_labels_raises_on_schema_violation(tmp_path):
    path = _write(tmp_path, "bad.jsonl", [{"case_id": "a1"}])
    with pytest.raises(ValueError):
        load_labels(path)


def test_split_agreement_separates_agreed_and_disagreement():
    labels_a = {"a1": _row("a1", "causal-audit"), "a2": _row("a2", "estimation")}
    labels_b = {"a1": _row("a1", "causal-audit"), "a2": _row("a2", "boundary-design")}
    agreed, disagreements, missing = split_agreement(labels_a, labels_b)
    assert [r["case_id"] for r in agreed] == ["a1"]
    assert disagreements == ["a2"]
    assert missing == []


def test_split_agreement_reports_case_ids_missing_from_one_rater():
    labels_a = {"a1": _row("a1", "causal-audit")}
    labels_b = {"a1": _row("a1", "causal-audit"), "a2": _row("a2", "estimation")}
    agreed, disagreements, missing = split_agreement(labels_a, labels_b)
    assert missing == ["a2"]


def test_adjudicate_third_pass_admits_on_2_of_3():
    labels_a = {"a1": _row("a1", "causal-audit")}
    labels_b = {"a1": _row("a1", "estimation")}
    labels_c = {"a1": _row("a1", "causal-audit")}
    adjudicated, discarded = adjudicate_third_pass(["a1"], labels_a, labels_b, labels_c)
    assert len(adjudicated) == 1
    assert adjudicated[0]["label"] == "causal-audit"
    assert discarded == []


def test_adjudicate_third_pass_discards_on_genuine_three_way_split():
    labels_a = {"a1": _row("a1", "causal-audit")}
    labels_b = {"a1": _row("a1", "estimation")}
    labels_c = {"a1": _row("a1", "boundary-design")}
    adjudicated, discarded = adjudicate_third_pass(["a1"], labels_a, labels_b, labels_c)
    assert adjudicated == []
    assert len(discarded) == 1
    assert discarded[0]["reason"] == "no-2-of-3-agreement"
