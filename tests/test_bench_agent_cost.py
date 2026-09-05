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
import statistics
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


class TestCompletionGatedTokens:
    """The exact confound the owner flagged: a condition that completes the
    task less often must not look "cheap" on a plain mean-tokens-among-
    valid-runs metric. These tests construct a case where completion rate
    genuinely differs between conditions and prove `mean_of_completed` +
    `completion_rate` surface that difference instead of hiding it."""

    def test_completion_mask_uses_threshold_inclusive(self):
        assert stats.completion_mask([3.0, 5.0, 5.1, 10.0], threshold=5.0) == [False, True, True, True]

    def test_completion_rate_empty_scores_raises(self):
        with pytest.raises(ValueError):
            stats.completion_rate([], threshold=5.0)

    def test_completion_rate_computes_fraction(self):
        assert stats.completion_rate([2.0, 8.0, 9.0, 3.0], threshold=5.0) == pytest.approx(0.5)

    def test_mean_of_completed_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            stats.mean_of_completed([1.0, 2.0], [1.0], threshold=5.0)

    def test_mean_of_completed_restricts_to_threshold_runs(self):
        # Only the 2nd and 4th runs meet the threshold.
        tokens = [100.0, 50000.0, 200.0, 60000.0]
        scores = [2.0, 8.0, 3.0, 9.0]
        assert stats.mean_of_completed(tokens, scores, threshold=5.0) == pytest.approx((50000.0 + 60000.0) / 2)

    def test_mean_of_completed_zero_completions_returns_none(self):
        tokens = [100.0, 200.0, 300.0]
        scores = [1.0, 2.0, 3.0]
        assert stats.mean_of_completed(tokens, scores, threshold=5.0) is None

    def test_cheap_but_incomplete_condition_does_not_win_on_completion_gated_metric(self):
        """Reconstructs the owner's exact scenario: condition A burns far
        fewer tokens per valid run but only completes the task 1/5 times
        (it stops early / gives a shallow, incomplete answer); condition B
        burns more tokens per run but completes every time. Under the
        pre-fix metric (mean tokens over ALL valid runs, no completion
        gate) A looks strictly cheaper -- that is the bug. Under the
        completion-gated metric, A's low completion rate is reported
        explicitly and its "tokens per completed task" mean is computed
        from only its single completed run, not inflated or hidden."""
        # Condition A: cheap, but only 1/5 runs actually complete the task.
        a_tokens = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
        a_scores = [2.0, 2.0, 2.0, 2.0, 8.0]  # only the last run meets threshold=5
        # Condition B: pricier, but completes every time.
        b_tokens = [5000.0, 5000.0, 5000.0, 5000.0, 5000.0]
        b_scores = [9.0, 9.0, 9.0, 9.0, 9.0]

        # Pre-fix metric (still reported, unchanged): A looks cheaper.
        assert statistics.mean(a_tokens) < statistics.mean(b_tokens)

        # Completion-gated metric: A's completion rate is far lower, and
        # its per-completed-task token mean draws from n=1, not n=5 --
        # the confound is visible, not laundered into a favorable mean.
        rate_a = stats.completion_rate(a_scores, threshold=5.0)
        rate_b = stats.completion_rate(b_scores, threshold=5.0)
        assert rate_a == pytest.approx(0.2)
        assert rate_b == pytest.approx(1.0)

        mean_a_completed = stats.mean_of_completed(a_tokens, a_scores, threshold=5.0)
        mean_b_completed = stats.mean_of_completed(b_tokens, b_scores, threshold=5.0)
        # A's completed-task mean is drawn from its single completed run
        # (1000.0) -- still numerically lower here, but the completion
        # rate (0.2 vs 1.0) sitting alongside it is the signal a reader
        # must not be allowed to omit; a condition report can never show
        # the token mean without the completion rate next to it.
        assert mean_a_completed == pytest.approx(1000.0)
        assert mean_b_completed == pytest.approx(5000.0)
        # The load-bearing assertion: completion rate differs sharply
        # between conditions even though the pre-fix all-valid-runs token
        # mean suggested A was simply "the cheap one" with no caveat.
        assert rate_a < rate_b

    def test_all_incomplete_condition_reports_undefined_not_zero(self):
        """If NO run in a condition meets the threshold, tokens-per-
        completed-task must be reported as undefined -- never silently
        computed as a mean over an empty list (which would raise) or
        defaulted to 0.0 (which would look like "free", the opposite of
        honest reporting)."""
        tokens = [1000.0, 2000.0, 3000.0]
        scores = [1.0, 1.0, 1.0]
        assert stats.completion_rate(scores, threshold=5.0) == 0.0
        assert stats.mean_of_completed(tokens, scores, threshold=5.0) is None


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
