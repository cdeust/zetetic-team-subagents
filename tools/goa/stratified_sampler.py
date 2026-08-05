"""stratified_sampler.py — per-shape allowlist filter + score-stratified sampling.

Implements EXTERNAL-TESTBASE.md §3 step 1 ("Sampling"): per shape, define a
tag/site allowlist, pull the top N stratified by score, target 40-60 candidates
per shape to survive downstream rejection. Corpus-agnostic: it consumes
`NormalizedRecord` (raw_record.py), never an XML/CSV format directly, so the
same function serves both the SE reader and the NTSB reader.

Stratification scheme: records are bucketed into quartiles by score, then drawn
proportionally across quartiles with a seeded PRNG. This bucket scheme is a
CURATION CONVENTION of this harness (not a measured or paper-sourced threshold)
— it exists so a target-N draw does not silently become "top N by score" (which
would over-represent already-popular, possibly-templated questions). Recorded
here, not invented silently, per rules/coding-standards.md §8.

precondition: `records` share one `corpus` and are candidates for exactly one
    shape (the caller has already applied the site/tag allowlist upstream via
    `matches_allowlist`).
postcondition: the returned list has between `min(target_max, len(records))` and
    `target_max` entries when >= target_min records are available; if fewer than
    target_min survive the allowlist, ALL of them are returned (never padded) and
    the caller must report the shortfall by named reason, never absorb it silently.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from tools.goa.raw_record import NormalizedRecord

DEFAULT_TARGET_MIN = 40
DEFAULT_TARGET_MAX = 60


def matches_allowlist(record: NormalizedRecord, tags: tuple[str, ...]) -> bool:
    """A record matches an allowlist entry if it carries at least one of `tags`,
    or the allowlist has no tags at all (site-only allowlist, e.g. skeptics.SE).
    """
    if not tags:
        return True
    return bool(set(record.tags) & set(tags))


@dataclass(frozen=True)
class SamplingResult:
    selected: list[NormalizedRecord]
    pool_size: int
    below_target_min: bool


def _quartile_buckets(records: list[NormalizedRecord]) -> list[list[NormalizedRecord]]:
    """Split `records` (sorted by score ascending, None treated as lowest) into
    4 roughly-equal buckets so a stratified draw spans low- and high-score posts.
    """
    ordered = sorted(records, key=lambda r: (r.score is None, r.score or 0))
    n = len(ordered)
    if n == 0:
        return [[], [], [], []]
    edges = [0, n // 4, n // 2, (3 * n) // 4, n]
    return [ordered[edges[i] : edges[i + 1]] for i in range(4)]


def stratified_sample(
    records: list[NormalizedRecord],
    target_min: int = DEFAULT_TARGET_MIN,
    target_max: int = DEFAULT_TARGET_MAX,
    seed: int = 20260805,
) -> SamplingResult:
    """Draw up to `target_max` records from `records`, spread across score
    quartiles. Deterministic: same (records, seed) => same draw, by sorting each
    bucket by source_id before the seeded shuffle (order-of-arrival independence).
    """
    pool_size = len(records)
    if pool_size <= target_max:
        return SamplingResult(selected=list(records), pool_size=pool_size, below_target_min=pool_size < target_min)
    buckets = _quartile_buckets(records)
    rng = random.Random(seed)
    per_bucket = target_max // 4
    remainder = target_max - per_bucket * 4
    selected: list[NormalizedRecord] = []
    for i, bucket in enumerate(buckets):
        ordered = sorted(bucket, key=lambda r: r.source_id)
        take = per_bucket + (1 if i < remainder else 0)
        take = min(take, len(ordered))
        selected.extend(rng.sample(ordered, take) if ordered else [])
    selected.sort(key=lambda r: r.source_id)
    return SamplingResult(selected=selected, pool_size=pool_size, below_target_min=False)
