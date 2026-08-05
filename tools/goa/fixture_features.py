"""fixture_features.py — locally-computed, non-reversible features for one
candidate's text, per EXTERNAL-TESTBASE.md §3 step 4(b): "never publish raw
question text verbatim in the CI-visible fixture ... locally-computed
features only, per Jacovi et al., 'Stop Uploading Test Data in Plain Text'
(EMNLP 2023)."

This applies to every retained corpus, not only the read-only SWE-bench/
Defects4J slices: item 4(a)-(c) of the curation protocol frames it as a
CONTAMINATION-resistance control (a public, verbatim-text fixture is exactly
the kind of artifact a future model could memorize), not a licensing
work-around — so the primary, redistributable corpora (SE, NTSB) get the same
treatment as the read-only slices. Resolved ambiguity, recorded in the PR
description: "CI-visible fixture" means ALL rows in external_testbase_v1.json,
regardless of which corpus's license would otherwise permit redistribution.

Every feature here is computable from `text` alone, with no external model
call (task constraint: no LLM/embedding calls in this pipeline) and no
reconstruction path back to the original text.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"\w+")
_CODE_BLOCK_RE = re.compile(r"```|<pre>|<code>")


def compute_features(text: str) -> dict:
    words = _WORD_RE.findall(text)
    word_count = len(words)
    avg_word_length = (sum(len(w) for w in words) / word_count) if word_count else 0.0
    return {
        "char_count": len(text),
        "word_count": word_count,
        "avg_word_length": round(avg_word_length, 3),
        "contains_code_block": bool(_CODE_BLOCK_RE.search(text)),
        "question_mark_count": text.count("?"),
    }


FORBIDDEN_ROW_FIELDS = ("text", "body", "raw_text", "question_body", "narrative_text", "narrative", "problem_statement", "issue_text")


def assert_no_raw_text(row: dict) -> list[str]:
    """Return named violations if `row` carries a forbidden raw-text field, at
    any nesting depth one level down (labeler_outputs.a.rationale is exempt —
    it is the labeler's own written judgment, not corpus text).
    """
    violations = [f"forbidden-field:{f}" for f in FORBIDDEN_ROW_FIELDS if f in row]
    return violations
