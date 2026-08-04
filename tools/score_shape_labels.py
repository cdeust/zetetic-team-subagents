#!/usr/bin/env python3
"""score_shape_labels.py — inter-rater agreement and adjudication for the Phase 0 gold set.

Phase 0 of the graph-of-agents refonte measures routing against a labelled problem
set (tasks/graph-of-agents-refonte.md). That set is only worth what its labels are
worth, so the agreement between independent blind labellers is reported BEFORE any
router score is computed: a routing accuracy quoted against a target the labellers
themselves cannot agree on is a number without a referent.

This tool does the arithmetic half ONLY. It assigns no labels and reads no case
text when scoring — it joins on `case_id`. Two jobs:

  1. AGREEMENT — pairwise Cohen's kappa for every pair of raters, plus Fleiss'
     kappa when three or more rate the same cases, plus raw agreement split by
     whether the case is routable (someone gave it a shape) or not (`none`).
  2. ADJUDICATION — with three raters, a case where two agree is settled by
     majority; a case where all three differ is a genuine three-way split and is
     emitted for human arbitration, never auto-resolved.

Kappa corrects raw agreement for agreement expected by chance. It is reported as a
bare number: no qualitative band ("moderate", "substantial") is printed, because
those bands are a convention (Landis & Koch 1977) contested for exactly this kind
of many-category, unbalanced task, and printing one would smuggle an interpretation
into a measurement (rules/coding-standards.md §8).

Sources for the two estimators, both implemented from the paper equations:
  - Cohen, J. (1960). "A Coefficient of Agreement for Nominal Scales."
    Educational and Psychological Measurement 20(1), 37-46. kappa = (p_o - p_e)/(1 - p_e)
  - Fleiss, J. L. (1971). "Measuring Nominal Scale Agreement Among Many Raters."
    Psychological Bulletin 76(5), 378-382. kappa = (P_bar - P_e)/(1 - P_e)

Every case dropped from a comparison is counted under a named reason and printed;
raters that labelled different case sets are intersected, never silently padded.

Exit codes: 0 report written, 2 usage error, 3 no case common to all raters.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

NONE_LABEL = "none"


def load_rater_labels(specs: list[str]) -> dict[str, dict[str, str]]:
    """Parse repeated NAME=PATH specs into {rater: {case_id: label}}.

    The same NAME may appear several times: a rater whose work was split across
    batches is one rater, and merging their files here keeps the batch split out
    of the statistics, where it has no meaning.
    """
    by_rater: dict[str, dict[str, str]] = defaultdict(dict)
    for spec in specs:
        name, sep, raw_path = spec.partition("=")
        if not sep or not name:
            raise ValueError(f"--rater expects NAME=PATH, got: {spec!r}")
        path = Path(raw_path).expanduser()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            case_id, label = row["case_id"], row["label"]
            if case_id in by_rater[name] and by_rater[name][case_id] != label:
                raise ValueError(
                    f"rater {name}: conflicting labels for {case_id} "
                    f"({by_rater[name][case_id]!r} vs {label!r})"
                )
            by_rater[name][case_id] = label
    return dict(by_rater)


def common_cases(by_rater: dict[str, dict[str, str]]) -> list[str]:
    """Case ids every rater labelled, sorted. Comparison is only defined here."""
    sets = [set(labels) for labels in by_rater.values()]
    return sorted(set.intersection(*sets)) if sets else []


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen (1960) kappa for two raters over paired nominal labels."""
    n = len(a)
    if n == 0:
        return float("nan")
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(
        (count_a[label] / n) * (count_b[label] / n)
        for label in set(count_a) | set(count_b)
    )
    if expected == 1.0:
        return float("nan")  # every rater used one single label: kappa undefined
    return (observed - expected) / (1.0 - expected)


def fleiss_kappa(rows: list[list[str]]) -> float:
    """Fleiss (1971) kappa: `rows[i]` holds every rater's label for case i."""
    n_cases = len(rows)
    if n_cases == 0:
        return float("nan")
    n_raters = len(rows[0])
    if n_raters < 2 or any(len(r) != n_raters for r in rows):
        return float("nan")
    categories = sorted({label for row in rows for label in row})
    counts = [Counter(row) for row in rows]
    agreement = [
        (sum(c[cat] ** 2 for cat in categories) - n_raters) / (n_raters * (n_raters - 1))
        for c in counts
    ]
    p_bar = sum(agreement) / n_cases
    marginals = [
        sum(c[cat] for c in counts) / (n_cases * n_raters) for cat in categories
    ]
    p_expected = sum(p**2 for p in marginals)
    if p_expected == 1.0:
        return float("nan")
    return (p_bar - p_expected) / (1.0 - p_expected)


def routable_split(a: list[str], b: list[str]) -> dict[str, int]:
    """Counts that separate 'is there a problem at all' from 'which shape'.

    Global agreement on this corpus is dominated by cases both raters call `none`,
    which says nothing about shape discrimination. These four counts keep the two
    questions apart so neither hides behind the other.
    """
    both_none = sum(1 for x, y in zip(a, b) if x == y == NONE_LABEL)
    routable_either = sum(
        1 for x, y in zip(a, b) if NONE_LABEL not in (x, y) or x != y
    )
    routable_both = sum(1 for x, y in zip(a, b) if x != NONE_LABEL and y != NONE_LABEL)
    shape_agreed = sum(
        1 for x, y in zip(a, b) if x == y and x != NONE_LABEL
    )
    return {
        "both_none": both_none,
        "routable_by_either": routable_either,
        "routable_by_both": routable_both,
        "shape_agreed": shape_agreed,
    }


def adjudicate(
    by_rater: dict[str, dict[str, str]], cases: list[str]
) -> tuple[list[dict], list[dict]]:
    """Split cases into (settled, three_way_splits).

    Settled means a strict majority of raters chose the same label — with two
    raters that is unanimity, with three it is 2-of-3. A case where every rater
    differs is NOT settled by picking one: it is returned for human arbitration,
    because a tie broken by rater order would encode the order as evidence.
    """
    names = sorted(by_rater)
    settled: list[dict] = []
    splits: list[dict] = []
    for case_id in cases:
        votes = {name: by_rater[name][case_id] for name in names}
        tally = Counter(votes.values()).most_common()
        top_label, top_count = tally[0]
        is_majority = top_count * 2 > len(names)
        tied = len(tally) > 1 and tally[1][1] == top_count
        record = {"case_id": case_id, "votes": votes}
        if is_majority and not tied:
            settled.append({**record, "label": top_label, "margin": f"{top_count}/{len(names)}"})
        else:
            splits.append(record)
    return settled, splits


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _report_agreement(by_rater: dict[str, dict[str, str]], cases: list[str]) -> None:
    names = sorted(by_rater)
    print(f"cases labelled by every rater: {len(cases)}")
    for name in names:
        extra = len(by_rater[name]) - len(cases)
        print(f"  rater {name}: {len(by_rater[name])} labelled ({extra} outside the common set)")
    print()
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            a = [by_rater[first][c] for c in cases]
            b = [by_rater[second][c] for c in cases]
            raw = sum(1 for x, y in zip(a, b) if x == y) / len(cases) if cases else 0.0
            split = routable_split(a, b)
            shape_denom = split["routable_by_either"]
            shape_rate = split["shape_agreed"] / shape_denom if shape_denom else 0.0
            print(f"{first} vs {second}:")
            print(f"  Cohen kappa           {cohen_kappa(a, b):.3f}")
            print(f"  raw agreement         {raw:.3f}  ({int(raw * len(cases))}/{len(cases)})")
            print(f"  both said none        {split['both_none']}")
            print(f"  routable by either    {shape_denom}")
            print(f"  agreed on the shape   {split['shape_agreed']}  ({shape_rate:.3f} of routable)")
            print()
    if len(names) >= 3:
        rows = [[by_rater[n][c] for n in names] for c in cases]
        print(f"Fleiss kappa ({len(names)} raters): {fleiss_kappa(rows):.3f}\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--rater",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="labels of one rater; repeat the same NAME to merge several files",
    )
    p.add_argument("--settled", type=Path, help="JSONL out: cases with a majority label")
    p.add_argument("--splits", type=Path, help="JSONL out: cases needing human arbitration")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        by_rater = load_rater_labels(args.rater)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"score_shape_labels: {exc}", file=sys.stderr)
        return 2
    if len(by_rater) < 2:
        print("score_shape_labels: need at least two raters", file=sys.stderr)
        return 2
    cases = common_cases(by_rater)
    if not cases:
        print("score_shape_labels: no case labelled by every rater", file=sys.stderr)
        return 3
    _report_agreement(by_rater, cases)
    settled, splits = adjudicate(by_rater, cases)
    print(f"settled by majority: {len(settled)}")
    print(f"needing arbitration: {len(splits)}")
    if args.settled:
        _write_jsonl(args.settled, settled)
        print(f"wrote {args.settled}")
    if args.splits:
        _write_jsonl(args.splits, splits)
        print(f"wrote {args.splits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
