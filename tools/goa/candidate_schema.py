"""candidate_schema.py — the one record shape every Instrument B curation step shares.

A "candidate" is one sampled post/record from a source corpus, before labeling.
Every downstream tool (dedupe, batch-building, concordance) reads and writes this
same shape, so the shape is defined once here rather than re-implied per script —
a schema drift between the sampler's output and the dedup tool's input would fail
silently as a KeyError three scripts downstream instead of at the boundary.

Fields carry exactly what curation needs and nothing a labeler should see before
adjudication: `text` is present here (labelers need it), but `site`/`tags`/`origin`
metadata that could bias a blind label is kept in `provenance`, stripped out by
build_labeler_batches.py before a batch reaches a labeler agent.

precondition: `text` is the literal body/narrative text pulled from the source
    corpus (SE post body, NTSB narrative field) with no truncation or normalization
    that would change its meaning.
postcondition: every accessor returns validated field types; `to_jsonl_row` never
    emits raw text under a fixture-facing key (that constraint lives in
    assemble_fixture.py, which never round-trips this class).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

REQUIRED_STR_FIELDS = ("case_id", "shape", "corpus", "text")


@dataclass(frozen=True)
class Provenance:
    """Where a candidate came from — kept out of labeler-visible batches."""

    corpus: str  # "stackexchange" | "ntsb"
    source_id: str  # SE post id, or NTSB occurrence id
    license: str
    site_or_dataset: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    score: int | None = None


@dataclass(frozen=True)
class Candidate:
    """One sampled, unlabeled candidate problem statement."""

    case_id: str
    shape: str
    corpus: str
    text: str
    provenance: Provenance

    def to_dict(self) -> dict:
        return asdict(self)

    def to_jsonl_row(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def validate_candidate_dict(row: dict) -> list[str]:
    """Return a list of named validation errors, empty if `row` is well-formed.

    Never raises — every caller (sampler, dedupe, batch builder) needs the SAME
    named-error list to report drops (rules/coding-standards.md §8: no silent
    loss), so validation is a pure function from dict to error list.
    """
    errors: list[str] = []
    for field_name in REQUIRED_STR_FIELDS:
        value = row.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing-or-empty:{field_name}")
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing-provenance")
        return errors
    for field_name in ("corpus", "source_id", "license", "site_or_dataset"):
        value = provenance.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing-or-empty:provenance.{field_name}")
    return errors


def candidate_from_dict(row: dict) -> Candidate:
    """Construct a `Candidate` from a validated dict. Raises on invalid input —
    callers must validate with `validate_candidate_dict` first if they need to
    report per-row errors instead of aborting.
    """
    errors = validate_candidate_dict(row)
    if errors:
        raise ValueError(f"invalid candidate row: {errors}")
    prov = row["provenance"]
    return Candidate(
        case_id=row["case_id"],
        shape=row["shape"],
        corpus=row["corpus"],
        text=row["text"],
        provenance=Provenance(
            corpus=prov["corpus"],
            source_id=prov["source_id"],
            license=prov["license"],
            site_or_dataset=prov["site_or_dataset"],
            tags=tuple(prov.get("tags", ())),
            score=prov.get("score"),
        ),
    )


def write_jsonl(path: Path, candidates: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for cand in candidates:
            fh.write(cand.to_jsonl_row() + "\n")


def read_jsonl(path: Path) -> tuple[list[Candidate], list[tuple[int, list[str]]]]:
    """Read a candidate JSONL file. Returns (valid candidates, [(line_no, errors)]).

    Malformed lines are reported by line number, not silently skipped — a caller
    that wants a hard-fail-on-any-error policy can check the second element.
    """
    candidates: list[Candidate] = []
    bad_lines: list[tuple[int, list[str]]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            bad_lines.append((line_no, [f"json-decode-error:{exc}"]))
            continue
        errors = validate_candidate_dict(row)
        if errors:
            bad_lines.append((line_no, errors))
            continue
        candidates.append(candidate_from_dict(row))
    return candidates, bad_lines
