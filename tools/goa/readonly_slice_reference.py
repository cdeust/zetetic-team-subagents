#!/usr/bin/env python3
"""readonly_slice_reference.py — build reference-only rows for the READ-ONLY
eval slices (SWE-bench, Defects4J), per user arbitration 2026-08-05: "stored as
(source_id, license) references + locally computed features ONLY, never raw
text in the repo" (mixed/unverified per-repo issue-report licensing,
EXTERNAL-TESTBASE.md §1 — these two corpora are NOT redistributed, unlike the
primary SE/NTSB corpora).

Input is a local, never-committed JSONL the operator builds themselves from
their own licensed local copy of SWE-bench/Defects4J
(source_id, license, corpus, text). This tool reads that file, computes
locally-derived features (fixture_features.py, shared with assemble_fixture.py
so the two corpora families cannot drift onto two different "what counts as
raw text" definitions), and writes ONLY the reference+features row — the input
file's `text` field never reaches the output.

Exit codes: 0 written, 2 usage/schema error, 3 no row survived.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.fixture_features import assert_no_raw_text, compute_features

ALLOWED_CORPORA = ("swebench", "defects4j")
REQUIRED_INPUT_FIELDS = ("source_id", "license", "corpus", "text")


def validate_input_row(row: dict) -> list[str]:
    errors = [f"missing-or-empty:{f}" for f in REQUIRED_INPUT_FIELDS if not str(row.get(f, "")).strip()]
    corpus = row.get("corpus")
    if corpus is not None and corpus not in ALLOWED_CORPORA:
        errors.append(f"unknown-corpus:{corpus!r} (expected one of {ALLOWED_CORPORA})")
    return errors


def build_reference_row(row: dict) -> dict:
    reference = {
        "source_id": row["source_id"],
        "license": row["license"],
        "corpus": row["corpus"],
        "shape_hint": row.get("shape_hint"),
        "features": compute_features(row["text"]),
    }
    violations = assert_no_raw_text(reference)
    if violations:
        raise ValueError(f"source_id {row['source_id']}: {violations}")
    return reference


def build_references(input_rows: list[dict]) -> tuple[list[dict], list[tuple[int, list[str]]]]:
    references: list[dict] = []
    bad_rows: list[tuple[int, list[str]]] = []
    for idx, row in enumerate(input_rows, start=1):
        errors = validate_input_row(row)
        if errors:
            bad_rows.append((idx, errors))
            continue
        references.append(build_reference_row(row))
    return references, bad_rows


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--local-input", type=Path, required=True, help="operator-local JSONL, never committed")
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_rows = []
    for line in args.local_input.read_text(encoding="utf-8").splitlines():
        if line.strip():
            input_rows.append(json.loads(line))
    references, bad_rows = build_references(input_rows)
    for idx, errors in bad_rows:
        print(f"readonly_slice_reference: row {idx}: {errors}", file=sys.stderr)
    if not references:
        print("readonly_slice_reference: no row survived", file=sys.stderr)
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for ref in references:
            fh.write(json.dumps(ref, ensure_ascii=False) + "\n")
    print(f"readonly_slice_reference: wrote {len(references)} reference rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
