#!/usr/bin/env python3
"""build_labeler_batches.py — strip provenance, emit a BLIND batch for labeler agents.

Per EXTERNAL-TESTBASE.md §3 step 3: "Each candidate is labelled independently by
two separate agent instances (different context, no shared state)". Both
instances label the SAME blind batch this tool produces — the independence is
in the labeler processes, not the input. A blind batch carries only
{case_id, text}: `site`, `tags`, `corpus`, and `shape` are withheld so a labeler
cannot shortcut its judgment by reading the SE tag that produced the candidate
(a labeler that saw `stats.SE tag=causality` before labeling would be scoring
the allowlist's hypothesis against itself, not against the rubric independently).

`--case-ids` restricts the batch to a named subset — used to build the third
adjudication batch (only the disagreement cases from concordance_gate.py's
`--emit-disagreements`), so the same blind-batch discipline applies there too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.candidate_schema import read_jsonl


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--case-ids",
        type=Path,
        help="optional file, one case_id per line: restrict the batch to these ids",
    )
    return p.parse_args(argv)


def build_blind_batch(candidates_path: Path, restrict_to: set[str] | None) -> tuple[list[dict], list]:
    candidates, bad_lines = read_jsonl(candidates_path)
    if restrict_to is not None:
        candidates = [c for c in candidates if c.case_id in restrict_to]
    rows = [{"case_id": c.case_id, "text": c.text} for c in candidates]
    return rows, bad_lines


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    restrict_to = None
    if args.case_ids:
        restrict_to = {
            line.strip() for line in args.case_ids.read_text(encoding="utf-8").splitlines() if line.strip()
        }
    rows, bad_lines = build_blind_batch(args.candidates, restrict_to)
    for line_no, errors in bad_lines:
        print(f"build_labeler_batches: line {line_no}: {errors}", file=sys.stderr)
    if not rows:
        print("build_labeler_batches: no candidates survived (empty batch)", file=sys.stderr)
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"build_labeler_batches: wrote {len(rows)} blind rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
