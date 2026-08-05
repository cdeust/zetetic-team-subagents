# GOA Scorecard: Phase 0 measurement record

This document is the binding reference for every routing score reported by the
graph-of-agents work. It states what was measured, what the numbers mean, what
they must never be quoted as, and which claims are structurally out of reach of
the current instruments. Scores reported without these caveats misstate the
measurement.

## 1. The gold set

351 real conversation turns, labelled against the frozen rubric
(`docs/goa-phase0/label-rubric.md`, 15 shapes + `none`).

| Quantity | Value |
|---|---|
| Cases | 351 (351 unique ids) |
| `none` | 281 (80.1%) |
| Routable | 70 |
| Shapes covered | 14 of 15 |
| Shapes with >= 5 cases | 5 |
| Not measured at all | `narrative-sensemaking` (zero cases) |

Labelling: two LLM raters (A, B) labelled every case; Cohen kappa 0.554
(287/351 raw). Disagreements (64) were adjudicated by a third LLM rater (C):
57 settled by 2-of-3 majority. The 7 genuine three-way splits were arbitrated
by the human author of the turns (2026-08-05): 6 resolved to A's label, 1 to
B's, 0 to `none`.

**Selection caveat (binding).** Those 7 cases were selected for maximal
disagreement. Neither "6/7 for A" nor "0 `none`" may be quoted as a general
agreement or boundary rate. The same rule applies to every pairwise statistic
computed on the 64-disagreement subset.

## 2. The 39% ceiling

Among cases both A and B routed, they agree on the shape 39.0% of the time
(41 shape agreements / 105 routable-by-either). This replicated to three
decimals against the earlier 120-case run: it is not a small-sample artefact.

**Reporting rule (binding).** Every shape-routing score is reported against
this ceiling, never against 100%. A router that matches the gold shape 39% of
the time has reached the measured agreement level of the raters who built the
gold set; claims above it are claims about exceeding the instrument.

## 3. Cross-model replay (Codex GPT-5.6, 2026-08-04)

Three model ids of one family (sol, terra, luna) relabelled all 351 cases
under the frozen protocol; all passes validated at 351 rows with no repair.
Inter-model Fleiss kappa 0.617. Details:
`docs/goa-phase0/REPLAY-CODEX-GPT56-2026-08-04.md`.

Four limits carried verbatim into any use of those figures:

1. Only 18 of the 64 A/B disagreements compare two different shapes; the
   other 46 are `none`/shape boundary calls. The headline shape-alignment
   table overstates how sharp the B lean is.
2. Routing propensities differ materially (A 71, B 93, Sol 136, Terra 99,
   Luna 148), so kappa mixes a boundary shift with genuine shape disagreement.
3. All passes ran under one OS user. A trace audit found zero cross-pass
   references, which corroborates but does not establish isolation.
4. Nothing was pre-registered: no threshold, no confidence interval. The
   agreement values are descriptive, never pass/fail.

The replay votes are validation evidence only. They are never folded with
A/B/C into a five- or six-rater majority.

## 4. Human countercheck: attempted, voided, retracted

A clinical-style blind re-labelling by the human arbiter was designed twice
and completed zero times.

- v1 (stratified 20/20 by gold label) was voided before labelling: stratifying
  by the labels under audit is the incorporation-bias failure (QUADAS-2,
  Whiting et al. 2011).
- v2 (simple random n=40, seed 20260806, agreement framing per Hui & Walter
  1980, coefficients per GRRAS) was frozen and delivered; the arbiter declined
  to label it. No labels were delivered, so the countercheck has NO result.
- A provisional scoring of an informal remark as if it were labels was made
  and then RETRACTED the same day. No figure from it may be quoted.

What remains true without the countercheck: the gold set's `none` boundary is
corroborated only by its internal raters, and the human arbiter's relation to
the consensus on unselected cases is unmeasured.

## 5. Known biases and reproducibility gaps

- A and B are different models: rater disagreement and model disagreement are
  confounded by design, declared and undisentangled.
- The labelling prompt for batches 1-2 (120 cases) was reconstructed, not
  archived: a declared reproducibility gap. Batch 3 onward is frozen.
- The gold set lives outside the repository (35 cases touch private work):
  third parties cannot replay the measurement.
- The arbiter of the 7 splits authored the underlying turns.

## 6. The two instruments

The corpus prevalence (80.1% `none`) and the coverage table make one corpus
unable to answer both routing questions. Two instruments, neither substituting
for the other:

| | Instrument A | Instrument B |
|---|---|---|
| Base | gold-351 (real turns) | external corpora (SE dump 2024-04-02 CC BY-SA 4.0, NTSB Zenodo 17096333 CC BY 4.0; SWE-bench/Defects4J as read-only slices) |
| Measures | `none`/routable boundary (abstention) | shape discrimination on real problem statements |
| Cannot measure | shape discrimination (63 routable / 14 shapes) | abstention (external items nearly always state a problem) |
| Metrics | raw agreement + Wilson CI + kappa + PABAK + AC1, prevalence reported (GRRAS; kappa alone is misleading at this skew, Feinstein & Cicchetti 1990) | per-shape accuracy against the 39% ceiling; shapes without external coverage declared not measured |
| Status | gold set frozen | curation pipeline + CI gates shipped (PR #99); fixture not yet built |

External coverage is 10 of 15 shapes. `narrative-sensemaking`,
`systems-leverage`, and `problem-reframing` have no verified external source
(see `EXTERNAL-TESTBASE.md`) and stay in the "not measured" column of any
Instrument B report.

## 7. Standing rules for future scores

1. Report against the ceiling (39%) and the prevalence (80.1%), never bare.
2. A shape with no measured cases is "not measured", never zero, never
   extrapolated.
3. Selection-biased subsets (the 64, the 7) never yield quotable rates.
4. Test tooling that copies the repository uses `git worktree` and cleans
   each run before the next (disk-exhaustion incident, 2026-08-04).
5. Any change to the label space (new shapes) invalidates gold labels made
   under the old rubric; relabel or version the gold set before scoring.
