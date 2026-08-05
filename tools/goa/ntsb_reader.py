"""ntsb_reader.py — read the NTSB accident-occurrence export (Zenodo record 17096333).

The Zenodo record's exact column layout was not fetched by this task (bulk
download is out of scope per task instructions — the export path is a CLI
argument, never fetched here), so this reader accepts BOTH of the two formats a
structured tabular export of this kind ships as in practice — CSV and JSON
Lines — selected by file extension, and takes the narrative-bearing column name
as a caller-supplied argument rather than a guessed constant. Guessing a column
name and hard-coding it would be exactly the "no source" failure
(rules/coding-standards.md §8): the design doc names the FIELDS that exist
("probable cause", "narrative") but not their literal header text.

precondition: `path` has extension `.csv` or `.jsonl`; `text_field` names a
    column/key present in every row (an absent field is a per-row drop, not a
    crash — one malformed export row must not abort the whole read).
postcondition: one `NormalizedRecord` per row with a non-empty `text_field`
    value; rows missing it are tallied under a named reason.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from tools.goa.raw_record import NormalizedRecord

NTSB_LICENSE = "CC BY 4.0 (Zenodo record 17096333)"
NTSB_DATASET_NAME = "ntsb-zenodo-17096333"


def _rows_from_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _rows_from_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_occurrences(
    path: Path,
    text_field: str,
    id_field: str = "occurrence_id",
) -> tuple[list[NormalizedRecord], Counter]:
    """Parse an NTSB occurrence export, returning (records, drop-reason tally)."""
    drops: Counter = Counter()
    if path.suffix == ".csv":
        rows = _rows_from_csv(path)
    elif path.suffix == ".jsonl":
        rows = _rows_from_jsonl(path)
    else:
        raise ValueError(f"unsupported NTSB export extension: {path.suffix!r} (expected .csv or .jsonl)")

    records: list[NormalizedRecord] = []
    for row in rows:
        source_id = row.get(id_field)
        text = row.get(text_field)
        if not source_id:
            drops[f"missing-field:{id_field}"] += 1
            continue
        if not text or not str(text).strip():
            drops[f"missing-field:{text_field}"] += 1
            continue
        records.append(
            NormalizedRecord(
                corpus="ntsb",
                source_id=str(source_id),
                text=str(text),
                site_or_dataset=NTSB_DATASET_NAME,
                license=NTSB_LICENSE,
                tags=(),
                score=None,
            )
        )
    return records, drops
