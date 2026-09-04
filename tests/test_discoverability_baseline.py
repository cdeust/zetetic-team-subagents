"""Unit tests for tools/tests/discoverability-baseline/score_routing.py's
pure scoring math (precision_recall). Does not invoke the `claude` CLI --
route_with_claude is exercised only by a live run of score_routing.py
itself (see docs/bench-agent-cost/README.md for the real baseline run).

Loaded by path: `discoverability-baseline` has hyphens, `score_routing.py`
has no dotted package (same convention as test_gen_bundle_sbom.py).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "tests" / "discoverability-baseline" / "score_routing.py"


def _load():
    spec = importlib.util.spec_from_file_location("discoverability_score_routing", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["discoverability_score_routing"] = module
    spec.loader.exec_module(module)
    return module


score_routing = _load()
SHAPE_IDS = ["boundary-design", "causal-audit", "none"]


class TestPrecisionRecall:
    def test_perfect_predictions_score_1_0(self):
        labels = {"p1": "boundary-design", "p2": "causal-audit", "p3": "none"}
        predictions = dict(labels)
        report = score_routing.precision_recall(predictions, labels, SHAPE_IDS)
        assert report["accuracy"] == 1.0
        assert report["per_shape"]["boundary-design"]["precision"] == 1.0
        assert report["per_shape"]["boundary-design"]["recall"] == 1.0

    def test_false_positive_lowers_precision_not_recall_of_true_shape(self):
        labels = {"p1": "boundary-design", "p2": "none"}
        predictions = {"p1": "boundary-design", "p2": "boundary-design"}
        report = score_routing.precision_recall(predictions, labels, SHAPE_IDS)
        bd = report["per_shape"]["boundary-design"]
        assert bd["tp"] == 1 and bd["fp"] == 1 and bd["fn"] == 0
        assert bd["precision"] == 0.5
        assert bd["recall"] == 1.0

    def test_false_negative_lowers_recall_not_precision(self):
        labels = {"p1": "boundary-design", "p2": "boundary-design"}
        predictions = {"p1": "boundary-design", "p2": "none"}
        report = score_routing.precision_recall(predictions, labels, SHAPE_IDS)
        bd = report["per_shape"]["boundary-design"]
        assert bd["tp"] == 1 and bd["fp"] == 0 and bd["fn"] == 1
        assert bd["precision"] == 1.0
        assert bd["recall"] == 0.5

    def test_shape_with_no_instances_reports_none_not_zero(self):
        labels = {"p1": "none"}
        predictions = {"p1": "none"}
        report = score_routing.precision_recall(predictions, labels, SHAPE_IDS)
        untested = report["per_shape"]["boundary-design"]
        assert untested["precision"] is None
        assert untested["recall"] is None

    def test_f1_is_harmonic_mean_of_precision_and_recall(self):
        labels = {"p1": "boundary-design", "p2": "boundary-design", "p3": "none"}
        predictions = {"p1": "boundary-design", "p2": "none", "p3": "boundary-design"}
        report = score_routing.precision_recall(predictions, labels, SHAPE_IDS)
        bd = report["per_shape"]["boundary-design"]
        # tp=1, fp=1, fn=1 -> precision=0.5, recall=0.5 -> f1=0.5
        assert bd["precision"] == 0.5
        assert bd["recall"] == 0.5
        assert bd["f1"] == 0.5


class TestBuildRouterPrompt:
    def test_includes_valid_ids_and_request_text(self):
        prompt = score_routing.build_router_prompt("TABLE TEXT", "fix the bug", ["a", "b", "none"])
        assert "TABLE TEXT" in prompt
        assert "fix the bug" in prompt
        assert "a, b, none" in prompt


class TestLabeledCorpus:
    """Structural sanity checks on the committed labeled_prompts.json --
    catches a corpus edit that breaks the scorer's assumptions before it
    reaches a live run."""

    def _corpus(self):
        corpus_path = REPO_ROOT / "tools" / "tests" / "discoverability-baseline" / "labeled_prompts.json"
        return json.loads(corpus_path.read_text(encoding="utf-8"))

    def test_corpus_has_at_least_20_prompts(self):
        corpus = self._corpus()
        assert len(corpus["prompts"]) >= 20

    def test_every_prompt_label_is_a_declared_shape_id(self):
        corpus = self._corpus()
        valid = set(corpus["shape_ids"])
        for p in corpus["prompts"]:
            assert p["label"] in valid, f"{p['id']} has undeclared label {p['label']!r}"

    def test_none_label_is_represented(self):
        corpus = self._corpus()
        labels = {p["label"] for p in corpus["prompts"]}
        assert "none" in labels

    def test_prompt_ids_are_unique(self):
        corpus = self._corpus()
        ids = [p["id"] for p in corpus["prompts"]]
        assert len(ids) == len(set(ids))
