"""labeler_schema.py — the frozen labeler-output record, shared by every tool
that reads or validates a labeler's file.

Schema per the task spec: {case_id, label, confidence, rationale}. Frozen means
callers must not add, rename, or loosen these fields without also updating this
module and every reader of it — it is the one seam between "a labeler agent ran"
and "the curation pipeline trusts the result."

`label` is deliberately NOT constrained to the 15-shape enum here: the frozen
Phase-0 rubric (referenced by EXTERNAL-TESTBASE.md §3 step 3) is a separate,
already-existing artifact this pipeline does not own or duplicate; the schema
check only enforces the labeler recorded ITS choice in the right shape, not that
the choice is a rubric member — that cross-check is `concordance_gate.py`'s job
against the second labeler's independent choice, not a static enum here.
"""

from __future__ import annotations

REQUIRED_FIELDS = ("case_id", "label", "confidence", "rationale")


def validate_label_row(row: dict) -> list[str]:
    """Return named validation errors for one labeler output row, empty if valid."""
    errors: list[str] = []
    for field_name in ("case_id", "label", "rationale"):
        value = row.get(field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing-or-empty:{field_name}")
    confidence = row.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        errors.append("missing-or-non-numeric:confidence")
    elif not (0.0 <= float(confidence) <= 1.0):
        errors.append("confidence-out-of-range:[0,1]")
    extra_fields = set(row) - set(REQUIRED_FIELDS)
    if extra_fields:
        errors.append(f"unexpected-fields:{sorted(extra_fields)}")
    return errors
