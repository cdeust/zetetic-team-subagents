#!/usr/bin/env python3
"""assemble_fixture.py — build/grow `external_testbase_v1.json` +manifest, per
EXTERNAL-TESTBASE.md §3 step 5.

Combines: the original candidates (for provenance + text-derived features,
never the text itself — see fixture_features.py), the concordance gate's
agreed rows, and (optionally) its adjudicated rows, into one frozen fixture.

Growing an EXISTING fixture (a later curation batch) is additive only: every
case_id already present must reproduce byte-identical, or the build aborts —
the same append-only contract fixture_freeze_gate.py enforces in CI, checked
here too so a local build catches a modification before it is ever committed.

Exit codes: 0 written, 2 usage/schema error, 3 no row survived assembly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.candidate_schema import Candidate, read_jsonl
from tools.goa.fixture_features import assert_no_raw_text, compute_features


def _read_rows_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def build_row(candidate: Candidate, concordance_row: dict, adjudication_trail: str) -> dict:
    prov = candidate.provenance
    row = {
        "case_id": candidate.case_id,
        "shape": candidate.shape,
        "label": concordance_row["label"],
        "source_id": prov.source_id,
        "license": prov.license,
        "site_or_dataset": prov.site_or_dataset,
        "tags": list(prov.tags),
        "score": prov.score,
        "features": compute_features(candidate.text),
        "labeler_outputs": concordance_row.get("labeler_outputs", {}),
        "adjudication_trail": adjudication_trail,
    }
    violations = assert_no_raw_text(row)
    if violations:
        raise ValueError(f"case_id {candidate.case_id}: {violations}")
    return row


def assemble_rows(
    candidates: list[Candidate],
    agreed: list[dict],
    adjudicated: list[dict],
) -> list[dict]:
    by_case_id = {c.case_id: c for c in candidates}
    rows: list[dict] = []
    for concordance_row, trail in [(r, "exact-agreement") for r in agreed] + [
        (r, "3rd-pass 2-of-3") for r in adjudicated
    ]:
        case_id = concordance_row["case_id"]
        candidate = by_case_id.get(case_id)
        if candidate is None:
            raise ValueError(f"case_id {case_id} has no matching candidate (provenance lost)")
        rows.append(build_row(candidate, concordance_row, trail))
    return rows


def merge_append_only(existing_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    """Union existing + new rows by case_id. Any case_id present in BOTH must be
    byte-identical (after canonical JSON serialization) — a change to an
    existing row is a freeze violation the build must refuse to produce, not
    only something CI catches after the fact.
    """
    by_case_id = {r["case_id"]: r for r in existing_rows}
    for row in new_rows:
        case_id = row["case_id"]
        if case_id in by_case_id:
            existing_canonical = json.dumps(by_case_id[case_id], sort_keys=True)
            new_canonical = json.dumps(row, sort_keys=True)
            if existing_canonical != new_canonical:
                raise ValueError(f"case_id {case_id}: existing fixture row would change — append-only violation")
            continue
        by_case_id[case_id] = row
    return sorted(by_case_id.values(), key=lambda r: r["case_id"])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidates", type=Path, action="append", required=True, help="repeatable")
    p.add_argument("--agreed", type=Path, required=True)
    p.add_argument("--adjudicated", type=Path)
    p.add_argument("--dump-date-se", default="2024-04-02")
    p.add_argument("--dump-date-ntsb", default="2025-09-11")
    p.add_argument(
        "--unmeasured-shapes",
        nargs="*",
        default=["narrative-sensemaking", "systems-leverage", "problem-reframing"],
    )
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    candidates: list[Candidate] = []
    for path in args.candidates:
        loaded, bad_lines = read_jsonl(path)
        for line_no, errors in bad_lines:
            print(f"assemble_fixture: {path}:{line_no}: {errors}", file=sys.stderr)
        candidates.extend(loaded)

    agreed = _read_rows_jsonl(args.agreed)
    adjudicated = _read_rows_jsonl(args.adjudicated) if args.adjudicated else []
    try:
        new_rows = assemble_rows(candidates, agreed, adjudicated)
    except ValueError as exc:
        print(f"assemble_fixture: {exc}", file=sys.stderr)
        return 2
    if not new_rows:
        print("assemble_fixture: no row survived assembly", file=sys.stderr)
        return 3

    existing_fixture = {"manifest": {}, "rows": []}
    if args.out.is_file():
        existing_fixture = json.loads(args.out.read_text(encoding="utf-8"))

    try:
        merged_rows = merge_append_only(existing_fixture.get("rows", []), new_rows)
    except ValueError as exc:
        print(f"assemble_fixture: {exc}", file=sys.stderr)
        return 2

    manifest = {
        "dump_date_stackexchange": args.dump_date_se,
        "dump_date_ntsb": args.dump_date_ntsb,
        "unmeasured_shapes": sorted(args.unmeasured_shapes),
        "row_count": len(merged_rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"manifest": manifest, "rows": merged_rows}, indent=2, sort_keys=True), encoding="utf-8")
    print(f"assemble_fixture: wrote {len(merged_rows)} rows ({len(new_rows)} new) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
