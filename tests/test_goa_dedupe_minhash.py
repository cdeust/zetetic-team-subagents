"""Unit tests for tools.goa.dedupe_minhash — Broder (1997) MinHash near-dup removal."""
from __future__ import annotations

from tools.goa.candidate_schema import Candidate, Provenance
from tools.goa.dedupe_minhash import (
    _hash_family,
    _stable_hash,
    dedupe,
    estimated_jaccard,
    minhash_signature,
    shingle,
)


def _candidate(case_id: str, text: str) -> Candidate:
    return Candidate(
        case_id=case_id,
        shape="causal-audit",
        corpus="stackexchange",
        text=text,
        provenance=Provenance(corpus="stackexchange", source_id=case_id, license="CC BY-SA 4.0", site_or_dataset="s"),
    )


def test_stable_hash_is_deterministic_across_calls():
    assert _stable_hash("some shingle text") == _stable_hash("some shingle text")


def test_shingle_below_size_returns_the_whole_text_as_one_shingle():
    assert shingle("a b c", size=5) == {"a b c"}


def test_shingle_empty_text_returns_empty_set():
    assert shingle("", size=5) == set()


def test_shingle_produces_overlapping_windows():
    result = shingle("a b c d e f", size=5)
    assert "a b c d e" in result
    assert "b c d e f" in result
    assert len(result) == 2


def test_minhash_signature_identical_shingle_sets_have_identical_signatures():
    hash_family = _hash_family(16, seed=1)
    sig_a = minhash_signature(shingle("the quick brown fox jumps over"), hash_family)
    sig_b = minhash_signature(shingle("the quick brown fox jumps over"), hash_family)
    assert sig_a == sig_b


def test_minhash_signature_disjoint_shingle_sets_estimate_low_jaccard():
    hash_family = _hash_family(64, seed=1)
    sig_a = minhash_signature(shingle("alpha beta gamma delta epsilon zeta"), hash_family)
    sig_b = minhash_signature(shingle("one two three four five six"), hash_family)
    assert estimated_jaccard(sig_a, sig_b) < 0.3


def test_minhash_signature_empty_shingles_returns_zero_signature():
    hash_family = _hash_family(8, seed=1)
    assert minhash_signature(set(), hash_family) == tuple(0 for _ in hash_family)


def test_estimated_jaccard_empty_signature_is_zero():
    assert estimated_jaccard((), ()) == 0.0


def test_dedupe_removes_near_identical_text_keeps_distinct_text():
    long_shared = "the same long question body repeated across two duplicate posts about causal inference " * 3
    candidates = [
        _candidate("aaa", long_shared),
        _candidate("bbb", long_shared + " typo"),  # a one-word trailing edit: near-identical shingle sets
        _candidate("ccc", "a completely different question about something else entirely, unrelated topic"),
    ]
    deduped, dropped_map = dedupe(candidates, threshold=0.85, num_hashes=64, seed=1)
    kept_ids = {c.case_id for c in deduped}
    assert "ccc" in kept_ids
    assert len(deduped) == 2  # one of aaa/bbb survives, ccc survives
    assert len(dropped_map) == 1


def test_dedupe_is_deterministic_given_the_same_seed():
    candidates = [_candidate(str(i), f"text number {i} about topic {i % 3}") for i in range(20)]
    first, _ = dedupe(candidates, seed=5)
    second, _ = dedupe(candidates, seed=5)
    assert [c.case_id for c in first] == [c.case_id for c in second]
