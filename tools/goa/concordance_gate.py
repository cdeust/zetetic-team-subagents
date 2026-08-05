#!/usr/bin/env python3
"""concordance_gate.py — two-labeler exact-agreement admission + 3rd-pass
adjudication, per EXTERNAL-TESTBASE.md §3 step 3.

Protocol implemented exactly as specified there: "Accept only on exact
agreement; disagreements go to a third adjudicating agent-pass with the rubric
text re-injected verbatim ... if the third pass doesn't produce 2-of-3
agreement, discard the item rather than force a label."

Two-stage CLI, mirroring the two-stage protocol:
  stage 1 (--labeler-a/-b only): split into agreed (admitted) vs. disagreement
    (case_ids only, for build_labeler_batches.py --case-ids to build the blind
    3rd-pass batch — this tool never re-injects the rubric text itself; rubric
    injection is the labeler-agent invocation's prompt, out of this tool's
    scope per the task's "do not embed any LLM calls").
  stage 2 (--labeler-a/-b/-c all given, restricted to the stage-1
    disagreement case_ids): apply the 2-of-3 rule; a genuine 3-way split is
    written to --emit-discarded, never force-labelled.

Exit codes: 0 ran to completion (some cases may still be discarded — that is
the protocol working, not a tool failure), 2 usage/schema error, 3 zero
common cases between the given labelers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.labeler_schema import validate_label_row


def load_labels(path: Path) -> dict[str, dict]:
    """Load one labeler's rows, keyed by case_id. Raises on the first schema
    violation — concordance is not a place to guess at a malformed row's intent.
    """
    labels: dict[str, dict] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        errors = validate_label_row(row)
        if errors:
            raise ValueError(f"{path}:{line_no}: {errors}")
        labels[row["case_id"]] = row
    return labels


def split_agreement(labels_a: dict[str, dict], labels_b: dict[str, dict]) -> tuple[list[dict], list[str], list[str]]:
    """Return (agreed rows, disagreement case_ids, case_ids missing from either file)."""
    common = sorted(set(labels_a) & set(labels_b))
    only_a = set(labels_a) - set(labels_b)
    only_b = set(labels_b) - set(labels_a)
    missing = sorted(only_a | only_b)
    agreed: list[dict] = []
    disagreements: list[str] = []
    for case_id in common:
        row_a, row_b = labels_a[case_id], labels_b[case_id]
        if row_a["label"] == row_b["label"]:
            agreed.append(
                {
                    "case_id": case_id,
                    "label": row_a["label"],
                    "labeler_outputs": {"a": row_a, "b": row_b},
                }
            )
        else:
            disagreements.append(case_id)
    return agreed, disagreements, missing


def adjudicate_third_pass(
    disagreement_ids: list[str],
    labels_a: dict[str, dict],
    labels_b: dict[str, dict],
    labels_c: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Apply the 2-of-3 rule. Returns (adjudicated rows, discarded records)."""
    adjudicated: list[dict] = []
    discarded: list[dict] = []
    for case_id in disagreement_ids:
        votes = {
            "a": labels_a[case_id]["label"],
            "b": labels_b[case_id]["label"],
            "c": labels_c[case_id]["label"],
        }
        tally = Counter(votes.values()).most_common()
        top_label, top_count = tally[0]
        if top_count >= 2:
            adjudicated.append(
                {
                    "case_id": case_id,
                    "label": top_label,
                    "labeler_outputs": {
                        "a": labels_a[case_id],
                        "b": labels_b[case_id],
                        "c": labels_c[case_id],
                    },
                    "adjudication_trail": "3rd-pass 2-of-3",
                }
            )
        else:
            discarded.append({"case_id": case_id, "votes": votes, "reason": "no-2-of-3-agreement"})
    return adjudicated, discarded


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            payload = {"case_id": row} if isinstance(row, str) else row
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--labeler-a", type=Path, required=True)
    p.add_argument("--labeler-b", type=Path, required=True)
    p.add_argument("--labeler-c", type=Path, help="3rd-pass adjudicator output (stage 2 only)")
    p.add_argument("--emit-agreed", type=Path)
    p.add_argument("--emit-disagreements", type=Path)
    p.add_argument("--emit-adjudicated", type=Path)
    p.add_argument("--emit-discarded", type=Path)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        labels_a = load_labels(args.labeler_a)
        labels_b = load_labels(args.labeler_b)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"concordance_gate: {exc}", file=sys.stderr)
        return 2

    agreed, disagreements, missing = split_agreement(labels_a, labels_b)
    if not agreed and not disagreements:
        print("concordance_gate: no case_id common to both labelers", file=sys.stderr)
        return 3
    if missing:
        print(f"concordance_gate: {len(missing)} case_id(s) labelled by only one rater: {missing}", file=sys.stderr)
    print(f"concordance_gate: {len(agreed)} agreed, {len(disagreements)} disagreement(s)")
    if args.emit_agreed:
        _write_jsonl(args.emit_agreed, agreed)
    if args.emit_disagreements:
        _write_jsonl(args.emit_disagreements, disagreements)

    if args.labeler_c:
        try:
            labels_c = load_labels(args.labeler_c)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"concordance_gate: {exc}", file=sys.stderr)
            return 2
        missing_c = [c for c in disagreements if c not in labels_c]
        if missing_c:
            print(f"concordance_gate: 3rd pass missing case_id(s): {missing_c}", file=sys.stderr)
            return 2
        adjudicated, discarded = adjudicate_third_pass(disagreements, labels_a, labels_b, labels_c)
        print(f"concordance_gate: 3rd pass — {len(adjudicated)} adjudicated, {len(discarded)} discarded")
        if args.emit_adjudicated:
            _write_jsonl(args.emit_adjudicated, adjudicated)
        if args.emit_discarded:
            _write_jsonl(args.emit_discarded, discarded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
