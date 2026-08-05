#!/usr/bin/env python3
"""sample_ntsb.py — draw candidate problem statements for one shape from the
NTSB Zenodo occurrence export (record 17096333), per EXTERNAL-TESTBASE.md §3.

Never fetches the Zenodo record; the export path is a required CLI argument.

Usage:
    python3 -m tools.goa.sample_ntsb \\
        --export ntsb_occurrences.csv \\
        --shape failure-forensics \\
        --text-field narrative \\
        --out candidates_failure_forensics_ntsb.jsonl

Exit codes: 0 candidates written, 2 usage/config error, 3 no candidate survived.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.candidate_schema import Candidate, Provenance, write_jsonl
from tools.goa.ntsb_reader import read_occurrences
from tools.goa.stratified_sampler import (
    DEFAULT_TARGET_MAX,
    DEFAULT_TARGET_MIN,
    stratified_sample,
)


def _report(drops, pool_size: int, selected: int, below_min: bool) -> None:
    print("sample_ntsb: drop tally", file=sys.stderr)
    for reason, n in sorted(drops.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<24} {n}", file=sys.stderr)
    print(f"  {'matched pool':<24} {pool_size}", file=sys.stderr)
    print(f"  {'selected':<24} {selected}", file=sys.stderr)
    if below_min:
        print(
            f"sample_ntsb: WARNING pool ({pool_size}) is below the target "
            f"minimum of {DEFAULT_TARGET_MIN}",
            file=sys.stderr,
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--export", type=Path, required=True, help=".csv or .jsonl occurrence export")
    p.add_argument("--shape", required=True)
    p.add_argument("--text-field", required=True, help="e.g. 'narrative' or 'probable_cause'")
    p.add_argument("--id-field", default="occurrence_id")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--target-min", type=int, default=DEFAULT_TARGET_MIN)
    p.add_argument("--target-max", type=int, default=DEFAULT_TARGET_MAX)
    p.add_argument("--seed", type=int, default=20260805)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        records, drops = read_occurrences(args.export, text_field=args.text_field, id_field=args.id_field)
    except (ValueError, OSError) as exc:
        print(f"sample_ntsb: {exc}", file=sys.stderr)
        return 2

    result = stratified_sample(records, target_min=args.target_min, target_max=args.target_max, seed=args.seed)
    _report(drops, result.pool_size, len(result.selected), result.below_target_min)

    if not result.selected:
        print("sample_ntsb: no candidate survived sampling", file=sys.stderr)
        return 3

    candidates = [
        Candidate(
            case_id=r.case_id,
            shape=args.shape,
            corpus="ntsb",
            text=r.text,
            provenance=Provenance(
                corpus="ntsb",
                source_id=r.source_id,
                license=r.license,
                site_or_dataset=r.site_or_dataset,
                tags=r.tags,
                score=r.score,
            ),
        )
        for r in result.selected
    ]
    write_jsonl(args.out, candidates)
    print(f"sample_ntsb: wrote {len(candidates)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
