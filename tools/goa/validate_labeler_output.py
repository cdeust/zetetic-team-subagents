#!/usr/bin/env python3
"""validate_labeler_output.py — validate one labeler's JSONL output against the
frozen schema {case_id, label, confidence, rationale} (labeler_schema.py).

This is the boundary check between "a labeler agent produced a file" and "the
curation pipeline trusts that file's shape" — concordance_gate.py assumes its
inputs already passed this check and does not re-validate field types itself,
so a schema drift is caught HERE, not three joins downstream as a KeyError.

Exit codes: 0 every row valid, 1 at least one row invalid, 2 usage/file error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.labeler_schema import validate_label_row


def validate_file(path: Path) -> list[tuple[int, list[str]]]:
    """Return [(line_no, errors)] for every invalid row; empty means all valid."""
    problems: list[tuple[int, list[str]]] = []
    seen_case_ids: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append((line_no, [f"json-decode-error:{exc}"]))
            continue
        errors = validate_label_row(row)
        case_id = row.get("case_id")
        if isinstance(case_id, str) and case_id in seen_case_ids:
            errors.append("duplicate-case-id")
        if isinstance(case_id, str):
            seen_case_ids.add(case_id)
        if errors:
            problems.append((line_no, errors))
    return problems


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--labels", type=Path, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.labels.is_file():
        print(f"validate_labeler_output: no such file: {args.labels}", file=sys.stderr)
        return 2
    problems = validate_file(args.labels)
    if not problems:
        print(f"validate_labeler_output: {args.labels} — all rows valid")
        return 0
    for line_no, errors in problems:
        print(f"validate_labeler_output: line {line_no}: {errors}", file=sys.stderr)
    print(f"validate_labeler_output: {len(problems)} invalid row(s) in {args.labels}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
