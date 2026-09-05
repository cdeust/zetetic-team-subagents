#!/usr/bin/env python3
"""Analyze one task's raw usage + scored-quality records: paired cost
comparison, paired quality comparison, and the pre-registered non-inferiority
verdict. Discards any run whose representation_check_passed is false
(Fisher discipline: a manipulation that didn't take is not data) and reports
the discard explicitly rather than silently dropping it.

Usage:
  tools/bench-agent-cost/analyze_results.py --raw-dir docs/bench-agent-cost/20260905/raw \\
      --scored-dir docs/bench-agent-cost/20260905/scored --task tasks/review_small_diff.json \\
      --non-inferiority-margin 1.0
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import stats as stats_lib  # noqa: E402
from lib import usage as usage_lib  # noqa: E402


def load_runs(raw_dir: Path, scored_dir: Path, task_id: str) -> list[dict]:
    runs = []
    for raw_path in sorted(raw_dir.glob(f"{task_id}_*.json")):
        record = json.loads(raw_path.read_text(encoding="utf-8"))
        scored_path = scored_dir / raw_path.name.replace(".json", ".scored.json")
        record["scores"] = json.loads(scored_path.read_text(encoding="utf-8")) if scored_path.exists() else None
        runs.append(record)
    return runs


def quality_score(record: dict) -> float | None:
    if not record["scores"]:
        return None
    # Average across the two blind evaluators (design doc: "blind by at
    # least two evaluators" -- neither evaluator alone is the score).
    totals = [e["total_points"] for e in record["scores"].values()]
    return statistics.mean(totals)


def group_by_condition(runs: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {"inline_skill": [], "subagent_spawn": []}
    for run in runs:
        grouped[run["provenance"]["condition"]].append(run)
    return grouped


def report_cost_metric(label: str, inline_vals: list[float], subagent_vals: list[float]) -> None:
    comparison = stats_lib.paired_comparison(inline_vals, subagent_vals)
    print(f"\n{label}:")
    print(f"  inline_skill:    mean={comparison.mean_a:.2f}")
    print(f"  subagent_spawn:  mean={comparison.mean_b:.2f}")
    print(f"  mean diff (inline - subagent): {comparison.mean_diff:.2f}")
    print(f"  paired t = {comparison.t_statistic:.3f}, df = {comparison.df}, "
          f"critical(two-tailed,0.05) = {comparison.critical_t_two_tailed_05}, "
          f"significant = {comparison.significant_at_05}")
    print(f"  seed-level: inline wins {comparison.wins_a}/{comparison.n}, "
          f"subagent wins {comparison.wins_b}/{comparison.n}, ties {comparison.ties}")


def report_discards(all_runs: list[dict], valid: list[dict], task_id: str) -> None:
    discarded = [r for r in all_runs if not r["representation_check_passed"]]
    print(f"Task: {task_id} | {len(valid)} valid runs, {len(discarded)} discarded (manipulation check failed)")
    for r in discarded:
        p = r["provenance"]
        print(f"  DISCARDED: rep {p['replication']} condition {p['condition']} "
              f"(subagents_spawned={r['usage_raw']['subagents_spawned']})")


def report_all_cost_metrics(inline_runs: list[dict], subagent_runs: list[dict]) -> None:
    report_cost_metric(
        "Total tokens (compute-proxy, NOT a carbon/energy claim)",
        [usage_lib.total_tokens(r["usage_raw"]) for r in inline_runs],
        [usage_lib.total_tokens(r["usage_raw"]) for r in subagent_runs],
    )
    report_cost_metric(
        "Wall-clock duration_ms (compute-proxy)",
        [r["usage_raw"]["duration_ms"] for r in inline_runs],
        [r["usage_raw"]["duration_ms"] for r in subagent_runs],
    )
    report_cost_metric(
        "total_cost_usd (derived pricing figure, CLI-reported)",
        [r["usage_raw"]["total_cost_usd"] for r in inline_runs],
        [r["usage_raw"]["total_cost_usd"] for r in subagent_runs],
    )


def report_quality(inline_runs: list[dict], subagent_runs: list[dict], task: dict, margin: float) -> None:
    inline_quality = [quality_score(r) for r in inline_runs]
    subagent_quality = [quality_score(r) for r in subagent_runs]
    if not all(q is not None for q in inline_quality + subagent_quality):
        print("\nQuality scores not available for all runs -- run score_quality.py first.")
        return
    report_cost_metric(f"Quality score (blind, mean of 2 evaluators, /{task['rubric_max_points']})",
                        inline_quality, subagent_quality)
    verdict = stats_lib.non_inferiority_verdict(inline_quality, subagent_quality, margin)
    print(f"\nPre-registered non-inferiority verdict (margin={margin}):")
    print(json.dumps(verdict, indent=2))


def report_completion_gated_tokens(inline_runs: list[dict], subagent_runs: list[dict], task: dict) -> None:
    """Report completion rate and tokens-per-completed-task per condition.

    Precondition: task carries a pre-registered `completion_threshold_points`
    (set alongside the rubric, before any run -- see task JSON's
    `completion_threshold_rationale`). Postcondition: prints, for each
    condition, the completion rate (never hidden) and the mean total-token
    count among only the runs that met the threshold -- reported as
    "undefined" rather than silently computed as a mean over zero runs when
    no run in a condition completed. This is additional to (never a
    replacement for) the existing "mean tokens among all valid runs" metric
    in report_all_cost_metrics, so a reader can see both figures side by
    side and judge whether a lower all-valid-runs mean was earned by
    actually finishing the task or by completing it less often.
    """
    threshold = task.get("completion_threshold_points")
    if threshold is None:
        print("\nCompletion-gated tokens: skipped -- task JSON has no "
              "'completion_threshold_points' (pre-registration requirement, "
              "see README). No completion-gated metric is computed without "
              "one; a global default would be an unsourced constant (§8).")
        return

    print(f"\nCompletion-gated tokens (threshold: score >= {threshold}/{task['rubric_max_points']} points):")
    for label, runs in (("inline_skill", inline_runs), ("subagent_spawn", subagent_runs)):
        quality = [quality_score(r) for r in runs]
        if any(q is None for q in quality):
            print(f"  {label}: skipped -- quality scores not available for all runs.")
            continue
        rate = stats_lib.completion_rate(quality, threshold)
        n_completed = sum(1 for q in quality if q >= threshold)
        print(f"  {label}: completion rate = {n_completed}/{len(runs)} ({rate:.0%})")
        tokens = [usage_lib.total_tokens(r["usage_raw"]) for r in runs]
        mean_completed = stats_lib.mean_of_completed(tokens, quality, threshold)
        if mean_completed is None:
            print(f"    tokens per completed task: 0 completed runs, metric undefined")
        else:
            print(f"    tokens per completed task: mean={mean_completed:.2f} (n={n_completed})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--scored-dir", required=True, type=Path)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--non-inferiority-margin", type=float, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task = json.loads(args.task.read_text(encoding="utf-8"))
    all_runs = load_runs(args.raw_dir, args.scored_dir, task["task_id"])
    valid = [r for r in all_runs if r["representation_check_passed"]]
    report_discards(all_runs, valid, task["task_id"])

    grouped = group_by_condition(valid)
    inline_runs, subagent_runs = grouped["inline_skill"], grouped["subagent_spawn"]
    n = min(len(inline_runs), len(subagent_runs))
    if n < 2:
        print(f"\nInsufficient paired valid runs (n={n}) for statistics; need >=2.")
        return 1
    inline_runs, subagent_runs = inline_runs[:n], subagent_runs[:n]

    report_all_cost_metrics(inline_runs, subagent_runs)
    report_quality(inline_runs, subagent_runs, task, args.non_inferiority_margin)
    report_completion_gated_tokens(inline_runs, subagent_runs, task)
    return 0


if __name__ == "__main__":
    sys.exit(main())
