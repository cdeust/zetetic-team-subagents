"""Minimal paired-sample statistics for the benchmark's analysis step
(Move 5: multi-seed discipline). No scipy/numpy dependency -- this repo
carries neither (checked 2026-09-05), and the sample sizes here (n=5-10
replications) are small enough that stdlib `statistics` plus a published
critical-value table is the honest, sourced choice over adding a heavy
dependency for one lookup.

Critical values source: NIST/SEMATECH e-Handbook of Statistical Methods,
Section 1.3.6.7 "Critical Values of the Student's t Distribution"
(https://www.itl.nist.gov/div898/handbook/eda/section3/eda3672.htm),
two-tailed alpha=0.05 and one-tailed alpha=0.05 columns, degrees of freedom
1-15 (covers every df this benchmark's minimum-5-replications protocol can
produce up to n=16 paired samples).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

# source: NIST/SEMATECH e-Handbook of Statistical Methods §1.3.6.7,
# two-tailed alpha = 0.05, df -> critical t value.
TWO_TAILED_05_CRITICAL_T = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
}

# source: same table, one-tailed alpha = 0.05 column, used for the
# pre-registered non-inferiority test (Move 5/6: one-sided by design).
ONE_TAILED_05_CRITICAL_T = {
    1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015,
    6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833, 10: 1.812,
    11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753,
}


@dataclass(frozen=True)
class PairedComparison:
    n: int
    mean_a: float
    mean_b: float
    mean_diff: float  # a - b
    stdev_diff: float
    t_statistic: float
    df: int
    critical_t_two_tailed_05: float | None
    significant_at_05: bool | None
    wins_a: int
    wins_b: int
    ties: int


def paired_comparison(a: list[float], b: list[float]) -> PairedComparison:
    """Precondition: a and b are same-length lists of per-seed scores for
    the same seeds, condition A and condition B respectively (Move 5:
    paired test, same seeds both sides). Postcondition: returns the paired
    t-test inputs/outputs; does not itself decide "wins" beyond a literal
    per-seed comparison."""
    if len(a) != len(b):
        raise ValueError(f"paired samples must be equal length: {len(a)} vs {len(b)}")
    n = len(a)
    if n < 2:
        raise ValueError("paired t-test requires at least 2 replications")

    diffs = [x - y for x, y in zip(a, b)]
    mean_diff = statistics.mean(diffs)
    stdev_diff = statistics.stdev(diffs)  # sample stdev, ddof=1
    df = n - 1

    t_statistic = mean_diff / (stdev_diff / (n ** 0.5)) if stdev_diff > 0 else float("inf")
    critical = TWO_TAILED_05_CRITICAL_T.get(df)
    significant = abs(t_statistic) > critical if critical is not None else None

    wins_a = sum(1 for x, y in zip(a, b) if x > y)
    wins_b = sum(1 for x, y in zip(a, b) if y > x)
    ties = n - wins_a - wins_b

    return PairedComparison(
        n=n,
        mean_a=statistics.mean(a),
        mean_b=statistics.mean(b),
        mean_diff=mean_diff,
        stdev_diff=stdev_diff,
        t_statistic=t_statistic,
        df=df,
        critical_t_two_tailed_05=critical,
        significant_at_05=significant,
        wins_a=wins_a,
        wins_b=wins_b,
        ties=ties,
    )


def non_inferiority_verdict(skill_scores: list[float], subagent_scores: list[float], margin: float) -> dict:
    """Pre-registered one-sided non-inferiority test (Move 5/design doc):
    H0: mean(skill) - mean(subagent) <= -margin (skill is worse by more
    than the margin); H1: mean(skill) - mean(subagent) > -margin (skill is
    non-inferior). Reject H0 (declare non-inferiority) when the one-sided
    lower confidence bound on the mean difference exceeds -margin.

    Precondition: margin > 0, decided before any run per the design doc.
    """
    if margin <= 0:
        raise ValueError("non-inferiority margin must be positive")
    n = len(skill_scores)
    diffs = [s - a for s, a in zip(skill_scores, subagent_scores)]
    mean_diff = statistics.mean(diffs)
    stdev_diff = statistics.stdev(diffs) if n > 1 else 0.0
    df = n - 1
    critical = ONE_TAILED_05_CRITICAL_T.get(df)

    se = stdev_diff / (n ** 0.5) if n > 0 else 0.0
    lower_bound = mean_diff - (critical * se if critical is not None else float("inf"))
    non_inferior = lower_bound > -margin if critical is not None else None

    return {
        "n": n,
        "margin": margin,
        "mean_diff_skill_minus_subagent": mean_diff,
        "stdev_diff": stdev_diff,
        "df": df,
        "one_tailed_critical_t_05": critical,
        "lower_confidence_bound_95": lower_bound,
        "non_inferior_at_05": non_inferior,
    }
