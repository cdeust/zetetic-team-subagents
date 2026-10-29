#!/usr/bin/env python3
"""ci_coverage.py -- reads a Cobertura report and fails under a line threshold.

The single CI (docs/superpowers/specs/2026-10-22-single-ci-design.md,
"Repository contract: ci.json") makes the ``unit`` step produce Cobertura XML
at ``coverage.xml`` and fails it under 90 % of lines, the same number for the
eight repositories. The root element's ``line-rate`` (0 to 1) is the figure
every producer here writes (coverage.py, cargo-llvm-cov, vitest/istanbul), so
one reader serves all stacks. Decimal arithmetic keeps 0.899 at 89.90, not at
a binary neighbour of the threshold.

This file is also embedded verbatim in ``templates/ci/pipeline.yml`` as an inline
``python3 -`` step: standard library only, arguments through ``sys.argv``.

Usage: ``python3 tools/ci_coverage.py coverage.xml [--min 90]``. Exit 0 at or
above the minimum, 1 under it, 2 when the report is absent or unreadable (an
unmeasurable coverage is not a pass).
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List

# source: docs/superpowers/specs/2026-10-22-single-ci-design.md, Constraints
# ("Coverage threshold: 90 % of lines ... same number for the eight repositories").
DEFAULT_MIN = Decimal("90")
# xml.etree stays, not defusedxml: the step must run on a bare runner with the
# standard library, and the report is written by the repository's own unit
# command in the same job. ElementTree does not expand external entities
# (https://docs.python.org/3/library/xml.html#xml-vulnerabilities, "Safe").


class CoverageError(Exception):
    """The report cannot be read as a Cobertura document with a line-rate."""


def percent(path: Path) -> Decimal:
    """Line coverage of ``path`` as a percentage with two decimals."""
    if not path.is_file():
        raise CoverageError(f"{path}: no such file")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CoverageError(f"{path}: not well-formed XML ({exc})") from exc
    if root.tag != "coverage":
        raise CoverageError(f"{path}: root element is <{root.tag}>, not <coverage>")
    raw = root.get("line-rate")
    if raw is None:
        raise CoverageError(f"{path}: <coverage> has no line-rate attribute")
    try:
        rate = Decimal(raw)
    except InvalidOperation as exc:
        raise CoverageError(f"{path}: line-rate {raw!r} is not a number") from exc
    return (rate * 100).quantize(Decimal("0.01"))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="fail when Cobertura line coverage is under a minimum")
    parser.add_argument("report", type=Path, help="Cobertura XML report")
    parser.add_argument("--min", type=Decimal, default=DEFAULT_MIN, help="minimum percentage of lines (default 90)")
    args = parser.parse_args(argv)
    try:
        value = percent(args.report)
    except CoverageError as exc:
        print(exc, file=sys.stderr)
        return 2
    minimum = args.min.quantize(Decimal("0.01"))
    if value < minimum:
        print(f"coverage: {value}% of lines, under the minimum {minimum}%")
        return 1
    print(f"coverage: {value}% of lines, minimum {minimum}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
