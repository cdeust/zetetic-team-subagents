"""Unit tests for tools.goa.stratified_sampler."""
from __future__ import annotations

from tools.goa.raw_record import NormalizedRecord
from tools.goa.stratified_sampler import matches_allowlist, stratified_sample


def _record(source_id: str, score: int, tags: tuple[str, ...] = ()) -> NormalizedRecord:
    return NormalizedRecord(
        corpus="stackexchange",
        source_id=source_id,
        text=f"text {source_id}",
        site_or_dataset="site",
        license="CC BY-SA 4.0",
        tags=tags,
        score=score,
    )


def test_matches_allowlist_with_no_tags_matches_everything():
    assert matches_allowlist(_record("1", 1, tags=()), tags=())


def test_matches_allowlist_requires_intersection():
    record = _record("1", 1, tags=("causality",))
    assert matches_allowlist(record, tags=("causality", "other"))
    assert not matches_allowlist(record, tags=("unrelated",))


def test_stratified_sample_returns_all_when_pool_below_target_max():
    records = [_record(str(i), i) for i in range(10)]
    result = stratified_sample(records, target_min=40, target_max=60)
    assert result.pool_size == 10
    assert result.below_target_min is True
    assert len(result.selected) == 10


def test_stratified_sample_caps_at_target_max_when_pool_is_large():
    records = [_record(str(i), i) for i in range(500)]
    result = stratified_sample(records, target_min=40, target_max=60, seed=1)
    assert result.pool_size == 500
    assert result.below_target_min is False
    assert len(result.selected) == 60


def test_stratified_sample_is_deterministic_given_the_same_seed():
    records = [_record(str(i), i % 20) for i in range(300)]
    first = stratified_sample(records, target_max=60, seed=42)
    second = stratified_sample(records, target_max=60, seed=42)
    assert [r.source_id for r in first.selected] == [r.source_id for r in second.selected]


def test_stratified_sample_spans_low_and_high_scores():
    records = [_record(str(i), i) for i in range(400)]  # scores 0..399
    result = stratified_sample(records, target_max=40, seed=7)
    scores = [r.score for r in result.selected]
    assert min(scores) < 100  # some from the low quartile
    assert max(scores) >= 300  # some from the high quartile
