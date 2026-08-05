"""raw_record.py — the corpus-agnostic record shape between a reader and the sampler.

Readers (se_dump_reader.py, ntsb_reader.py) each know one file format. The
stratified sampler (stratified_sampler.py) knows shapes, allowlists and score
bucketing but nothing about XML or CSV. `NormalizedRecord` is the seam: every
reader emits this shape, so a new corpus reader (a future addition) plugs into
the same sampler without the sampler changing at all (OCP, rules/coding-standards
§1.2 — a new corpus is a new reader, zero edits to stratified_sampler.py).

precondition: `text` is verbatim source text (no truncation); `score` is None
    when the source has no vote/quality signal (e.g. a source lacking scores).
postcondition: `case_id` is a deterministic content hash of (corpus, source_id,
    text) — stable across runs, unique per (corpus, source_id) pair even if two
    corpora reuse the same source_id numbering.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NormalizedRecord:
    corpus: str
    source_id: str
    text: str
    site_or_dataset: str
    license: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    score: int | None = None

    @property
    def case_id(self) -> str:
        payload = f"{self.corpus}:{self.source_id}:{self.text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]
