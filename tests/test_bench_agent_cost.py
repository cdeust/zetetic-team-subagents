"""Unit tests for tools/bench-agent-cost/lib/{usage,stats}.py -- the pure
functions in the Phase 3 paired cost/quality benchmark harness (no
subprocess calls, no network I/O, so these run in CI without invoking the
`claude` CLI).

Loaded by path: `bench-agent-cost` has a hyphen and is not a valid dotted
package name (same convention as test_gen_bundle_sbom.py for
tools/gen-bundle-sbom.py).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "tools" / "bench-agent-cost" / "lib"


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, LIB_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    # dataclasses' field-type resolution looks the module up in sys.modules
    # by __module__ name, so it must be registered before exec_module runs.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


usage = _load("bench_agent_cost_usage", "usage.py")
stats = _load("bench_agent_cost_stats", "stats.py")


def _sample_cli_result(**overrides):
    base = {
        "session_id": "abc-123",
        "total_cost_usd": 0.2069225,
        "duration_ms": 3756,
        "duration_api_ms": 2976,
        "num_turns": 1,
        "is_error": False,
        "subtype": "success",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 89,
            "cache_creation_input_tokens": 102553,
            "cache_read_input_tokens": 13615,
        },
        "subagent_stats": {"spawned": 0},
    }
    base.update(overrides)
    return base


class TestExtractUsage:
    def test_extracts_all_required_fields(self):
        row = usage.extract_usage(_sample_cli_result())
        assert row["input_tokens"] == 10
        assert row["output_tokens"] == 89
        assert row["total_cost_usd"] == pytest.approx(0.2069225)
        assert row["subagents_spawned"] == 0

    def test_missing_top_level_field_raises(self):
        bad = _sample_cli_result()
        del bad["total_cost_usd"]
        with pytest.raises(usage.MalformedCliOutputError):
            usage.extract_usage(bad)

    def test_missing_usage_field_raises(self):
        bad = _sample_cli_result()
        del bad["usage"]["output_tokens"]
        with pytest.raises(usage.MalformedCliOutputError):
            usage.extract_usage(bad)

    def test_defaults_subagents_spawned_when_stats_absent(self):
        bad = _sample_cli_result()
        del bad["subagent_stats"]
        row = usage.extract_usage(bad)
        assert row["subagents_spawned"] == 0


class TestTotalTokens:
    def test_sums_all_four_fields(self):
        row = usage.extract_usage(_sample_cli_result())
        assert usage.total_tokens(row) == 10 + 89 + 102553 + 13615


class TestConditionMatchesRepresentation:
    def test_subagent_condition_requires_a_spawn(self):
        row = usage.extract_usage(_sample_cli_result(subagent_stats={"spawned": 1}))
        assert usage.condition_matches_representation(row, "subagent_spawn") is True
        row_zero = usage.extract_usage(_sample_cli_result())
        assert usage.condition_matches_representation(row_zero, "subagent_spawn") is False

    def test_inline_condition_requires_zero_spawns(self):
        row = usage.extract_usage(_sample_cli_result())
        assert usage.condition_matches_representation(row, "inline_skill") is True
        row_spawned = usage.extract_usage(_sample_cli_result(subagent_stats={"spawned": 2}))
        assert usage.condition_matches_representation(row_spawned, "inline_skill") is False

    def test_unknown_condition_raises(self):
        row = usage.extract_usage(_sample_cli_result())
        with pytest.raises(ValueError):
            usage.condition_matches_representation(row, "bogus")


class TestPairedComparison:
    def test_identical_samples_have_zero_diff_and_no_significance(self):
        a = [5.0, 5.0, 5.0, 5.0, 5.0]
        b = [5.0, 5.0, 5.0, 5.0, 5.0]
        comparison = stats.paired_comparison(a, b)
        assert comparison.mean_diff == 0.0
        assert comparison.wins_a == 0 and comparison.wins_b == 0 and comparison.ties == 5

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            stats.paired_comparison([1.0, 2.0], [1.0])

    def test_too_few_replications_raise(self):
        with pytest.raises(ValueError):
            stats.paired_comparison([1.0], [2.0])

    def test_clear_effect_is_flagged_significant(self):
        # Large, consistent per-seed gap should cross the df=4 critical
        # value (2.776, NIST/SEMATECH table) with tight variance.
        a = [100.0, 101.0, 99.0, 100.0, 100.0]
        b = [10.0, 11.0, 9.0, 10.0, 10.0]
        comparison = stats.paired_comparison(a, b)
        assert comparison.significant_at_05 is True
        assert comparison.wins_a == 5


class TestNonInferiorityVerdict:
    def test_positive_margin_required(self):
        with pytest.raises(ValueError):
            stats.non_inferiority_verdict([1.0, 2.0], [1.0, 2.0], margin=0.0)

    def test_equal_scores_are_non_inferior(self):
        skill = [8.0, 8.0, 8.0, 8.0, 8.0]
        subagent = [8.0, 8.0, 8.0, 8.0, 8.0]
        verdict = stats.non_inferiority_verdict(skill, subagent, margin=1.0)
        assert verdict["non_inferior_at_05"] is True

    def test_large_consistent_deficit_beyond_margin_is_not_non_inferior(self):
        skill = [3.0, 3.0, 3.0, 3.0, 3.0]
        subagent = [9.0, 9.0, 9.0, 9.0, 9.0]
        verdict = stats.non_inferiority_verdict(skill, subagent, margin=1.0)
        assert verdict["non_inferior_at_05"] is False
