#!/usr/bin/env python3
"""dedupe_minhash.py — near-duplicate removal on candidate JSONL, per
EXTERNAL-TESTBASE.md §3 step 2: "SE sites contain heavy templated/duplicate
questions ... near-duplicate removal via MinHash/SimHash on question-body text."

Technique: MinHash signature estimation of Jaccard similarity between shingle
sets. source: Broder, A. Z. (1997). "On the resemblance and containment of
documents." Proceedings of Compression and Complexity of Sequences 1997,
IEEE, pp. 21-29. DOI 10.1109/SEQUEN.1997.666900. Equation implemented:
for a random permutation pi of the shingle universe, Pr[min(pi(A)) ==
min(pi(B))] == |A intersect B| / |A union B| (Broder 1997, Theorem 1);
`num_hashes` independent linear hash functions approximate `num_hashes`
independent permutations (the standard universal-hashing MinHash
implementation, e.g. Leskovec, Rajaraman & Ullman, "Mining of Massive
Datasets" 3rd ed. 2020, ch. 3.3).

Constants NOT sourced from a paper (pre-registered choices, per
rules/coding-standards.md §8c — recorded here and in the manifest rather than
invented silently):
  - SHINGLE_SIZE = 5 (word shingles): a convention of this harness for
    natural-language SE/NTSB text, not a measured optimum for this corpus.
  - NUM_HASHES = 64: trades signature precision (estimator std error ~
    1/sqrt(num_hashes), Broder 1997 §3) against per-candidate compute; a
    pool of tens of candidates per shape does not need thousands.
  - JACCARD_THRESHOLD = 0.85: the near-duplicate acceptance bar. Kept high
    (near-identical, not merely similar) because two independently-written
    SE answers about the same topic are expected to share vocabulary without
    being duplicates.

Clustering: greedy union-find over pairs whose ESTIMATED Jaccard (signature
match rate) exceeds JACCARD_THRESHOLD. Exactly one representative survives
per cluster — the lowest case_id, for deterministic output independent of
input file order.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.goa.candidate_schema import Candidate, read_jsonl, write_jsonl

SHINGLE_SIZE = 5  # pre-registered convention, see module docstring
NUM_HASHES = 64  # pre-registered convention, see module docstring
JACCARD_THRESHOLD = 0.85  # pre-registered convention, see module docstring

_WORD_RE = re.compile(r"\w+")

# 64 (a, b) pairs for h_i(x) = (a*x + b) mod MERSENNE_PRIME, a fixed odd prime
# modulus so the family is a valid universal hash family (Carter & Wegman 1979,
# the standard construction MinHash implementations use). Seeded deterministically
# so the same corpus always produces the same signatures across runs.
_MERSENNE_PRIME = (1 << 61) - 1


def _hash_family(num_hashes: int, seed: int) -> list[tuple[int, int]]:
    import random

    rng = random.Random(seed)
    return [(rng.randrange(1, _MERSENNE_PRIME), rng.randrange(0, _MERSENNE_PRIME)) for _ in range(num_hashes)]


def shingle(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    """Word-level shingles: contiguous runs of `size` lowercase word tokens."""
    words = _WORD_RE.findall(text.lower())
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def _stable_hash(shingle_text: str) -> int:
    """Deterministic integer hash for a shingle. Python's builtin `hash(str)` is
    salted per-process (PYTHONHASHSEED) for security and would make every
    signature — and therefore every dedup decision — irreproducible across
    runs/machines; sha256 is stable by construction.
    """
    digest = hashlib.sha256(shingle_text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def minhash_signature(shingles: set[str], hash_family: list[tuple[int, int]]) -> tuple[int, ...]:
    """Broder (1997) Theorem 1 estimator: one minimum per hash function."""
    if not shingles:
        return tuple(0 for _ in hash_family)
    hashed = [_stable_hash(s) & _MERSENNE_PRIME for s in shingles]
    return tuple(min((a * x + b) % _MERSENNE_PRIME for x in hashed) for a, b in hash_family)


def estimated_jaccard(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    """Fraction of matching signature positions estimates Jaccard similarity."""
    if not sig_a:
        return 0.0
    matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
    return matches / len(sig_a)


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def dedupe(
    candidates: list[Candidate],
    threshold: float = JACCARD_THRESHOLD,
    num_hashes: int = NUM_HASHES,
    seed: int = 20260805,
) -> tuple[list[Candidate], dict[str, str]]:
    """Return (deduplicated candidates, {dropped_case_id: kept_case_id})."""
    hash_family = _hash_family(num_hashes, seed)
    signatures = {c.case_id: minhash_signature(shingle(c.text), hash_family) for c in candidates}
    uf = _UnionFind([c.case_id for c in candidates])
    ids = sorted(signatures)
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            if estimated_jaccard(signatures[id_a], signatures[id_b]) >= threshold:
                uf.union(id_a, id_b)
    by_case_id = {c.case_id: c for c in candidates}
    kept: dict[str, Candidate] = {}
    dropped_map: dict[str, str] = {}
    for case_id in ids:
        representative = uf.find(case_id)
        kept.setdefault(representative, by_case_id[representative])
        if case_id != representative:
            dropped_map[case_id] = representative
    return sorted(kept.values(), key=lambda c: c.case_id), dropped_map


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--in", dest="in_path", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=JACCARD_THRESHOLD)
    p.add_argument("--num-hashes", type=int, default=NUM_HASHES)
    p.add_argument("--seed", type=int, default=20260805)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    candidates, bad_lines = read_jsonl(args.in_path)
    if bad_lines:
        for line_no, errors in bad_lines:
            print(f"dedupe_minhash: line {line_no}: {errors}", file=sys.stderr)
    if not candidates:
        print("dedupe_minhash: no valid candidates in input", file=sys.stderr)
        return 3
    deduped, dropped_map = dedupe(candidates, threshold=args.threshold, num_hashes=args.num_hashes, seed=args.seed)
    write_jsonl(args.out, deduped)
    print(f"dedupe_minhash: {len(candidates)} in, {len(deduped)} kept, {len(dropped_map)} near-duplicates dropped")
    for dropped_id, kept_id in sorted(dropped_map.items()):
        print(f"  {dropped_id} -> duplicate of {kept_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
