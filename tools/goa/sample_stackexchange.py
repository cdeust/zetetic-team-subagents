#!/usr/bin/env python3
"""sample_stackexchange.py — draw candidate problem statements for one shape from
one Stack Exchange site's `Posts.xml`, per EXTERNAL-TESTBASE.md §3 step 1.

This tool never fetches or downloads the SE dump; the Posts.xml path is a
required CLI argument, supplied by the operator who already has the archive.org
2024-04-02 dump on disk (task constraint — 92 GB is out of scope to move here).

Usage:
    python3 -m tools.goa.sample_stackexchange \\
        --posts-xml /path/to/stats.stackexchange.com/Posts.xml \\
        --shape causal-audit \\
        --shape-map tools/goa/shape_corpus_map.json \\
        --out candidates_causal_audit.jsonl

Exit codes: 0 candidates written, 2 usage/config error, 3 no candidate survived.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.candidate_schema import Candidate, Provenance, write_jsonl
from tools.goa.se_dump_reader import read_posts
from tools.goa.stratified_sampler import (
    DEFAULT_TARGET_MAX,
    DEFAULT_TARGET_MIN,
    stratified_sample,
)


def load_shape_config(shape_map_path: Path, shape: str) -> dict:
    config = json.loads(shape_map_path.read_text(encoding="utf-8"))
    shapes = config.get("shapes", {})
    if shape not in shapes:
        raise KeyError(f"shape {shape!r} not present in {shape_map_path}")
    entry = shapes[shape]
    if entry.get("corpus") != "stackexchange":
        raise ValueError(f"shape {shape!r} is not mapped to corpus 'stackexchange' in {shape_map_path}")
    return entry


def _report(drops, pool_size: int, selected: int, below_min: bool) -> None:
    print("sample_stackexchange: drop tally", file=sys.stderr)
    for reason, n in sorted(drops.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<24} {n}", file=sys.stderr)
    print(f"  {'matched pool':<24} {pool_size}", file=sys.stderr)
    print(f"  {'selected':<24} {selected}", file=sys.stderr)
    if below_min:
        print(
            f"sample_stackexchange: WARNING pool ({pool_size}) is below the "
            f"target minimum of {DEFAULT_TARGET_MIN} — allowlist may need revisiting",
            file=sys.stderr,
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--posts-xml", type=Path, required=True)
    p.add_argument("--shape", required=True)
    p.add_argument(
        "--shape-map",
        type=Path,
        default=Path(__file__).resolve().parent / "shape_corpus_map.json",
    )
    p.add_argument("--license", default="CC BY-SA 4.0 (archive.org 2024-04-02 dump)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--target-min", type=int, default=DEFAULT_TARGET_MIN)
    p.add_argument("--target-max", type=int, default=DEFAULT_TARGET_MAX)
    p.add_argument("--seed", type=int, default=20260805)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        shape_cfg = load_shape_config(args.shape_map, args.shape)
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"sample_stackexchange: {exc}", file=sys.stderr)
        return 2

    site = shape_cfg["site"]
    tags = tuple(shape_cfg.get("tags", ()))
    records, drops = read_posts(args.posts_xml, site=site, license_str=args.license, tag_allowlist=tags)
    result = stratified_sample(records, target_min=args.target_min, target_max=args.target_max, seed=args.seed)
    _report(drops, result.pool_size, len(result.selected), result.below_target_min)

    if not result.selected:
        print("sample_stackexchange: no candidate survived sampling", file=sys.stderr)
        return 3

    candidates = [
        Candidate(
            case_id=r.case_id,
            shape=args.shape,
            corpus="stackexchange",
            text=r.text,
            provenance=Provenance(
                corpus="stackexchange",
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
    print(f"sample_stackexchange: wrote {len(candidates)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
