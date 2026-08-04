# Phase 0 protocol — replayable labelling and agreement measurement

This directory holds everything needed to REPRODUCE the Phase 0 labelling of the
graph-of-agents refonte with an independent set of labellers, on any model family.

It deliberately holds no cases. See "Getting the cases" below — that gap is the
point of this document, not an oversight.

## What Phase 0 measures, and what it found

A routing benchmark scores a router against an expected shape per case. That score
is meaningless if independent readers cannot agree on the expected shape in the
first place. So agreement is measured BEFORE any router runs.

Measured on 351 mined cases, two blind labellers (different models), one frozen rubric:

| | 120 cases | 351 cases |
|---|---|---|
| Cohen's kappa | 0.560 | 0.554 |
| no routable problem stated (both) | 79 (66%) | 246 (70%) |
| routable by at least one | 41 | 105 |
| agreed on the shape | 16 = **39.0%** | 41 = **39.0%** |

The 39% figure replicated exactly when the corpus was tripled. It is not a
small-sample artefact: it is the ceiling any routing accuracy on this corpus must
be reported against. A router scored against 100% would be scored against a target
its own labellers cannot locate.

Adjudication of the 64 disagreements by a third blind labeller settled 57 by 2-of-3
majority and left 7 genuine three-way splits for human arbitration.

**Open confound, and the reason this protocol is published.** The third labeller
agreed with labeller B far more than with labeller A (20 shape agreements vs 2).
Two readings cannot be separated with same-family raters: either B is right more
often, or all three raters share a model family and the majority merely ratifies a
shared prior. Replaying this protocol on a DIFFERENT model family is the test that
separates them. If cross-family agreement is markedly below within-family
agreement, part of the measured kappa is family, not rubric ambiguity.

## Files

| File | Role |
|---|---|
| `label-rubric.md` | The 15 shapes + `none`, descriptions copied verbatim from each skill's `description:` frontmatter — exactly what the router sees. FROZEN before any case was read. |
| `labeling-prompt.md` | The instruction handed to every labeller, identical for all. FROZEN. |
| `../../tools/mine_shape_cases.py` | Mines unlabelled candidates from session transcripts. |
| `../../tools/score_shape_labels.py` | Cohen (1960) and Fleiss (1971) kappa, majority adjudication, three-way-split extraction. |

## Replaying it

1. **Mine candidates** (or receive them — see below):

   ```
   python3 tools/mine_shape_cases.py --out cases.jsonl --sample 0
   ```

   Deterministic: same corpus + same seed gives byte-identical output. Every dropped
   turn is counted under a named reason and printed to stderr.

2. **Label blind, one labeller per model.** Hand each labeller `labeling-prompt.md`
   verbatim, substituting `<CASES_PATH>` and `<OUT_PATH>`. Where the prompt refers to
   `~/.claude/goa-phase0/label-rubric.md`, read it as this directory's copy — the path
   is left as-is because the prompt is frozen and must not be edited between runs.

   Constraint 5 of the prompt is the load-bearing one: a labeller who sees another
   labeller's output destroys the measurement. Enforce it.

3. **Score:**

   ```
   python3 tools/score_shape_labels.py \
     --rater A=labels-A.jsonl --rater B=labels-B.jsonl \
     --settled settled.jsonl --splits disagreements.jsonl
   ```

   `--rater NAME=PATH` repeats; the same NAME repeated merges that rater's files, so a
   labeller whose work was split across batches stays one rater.

4. **Adjudicate.** Build a cases file from the disagreement ids containing `case_id`
   and `text` ONLY — no votes — and hand it to a third labeller under the same prompt.
   Re-run the scorer with three raters. Cases where all three differ are NOT
   auto-resolved: a tie broken by rater order would encode the order as evidence.

   Note when reading that run: the pairwise kappas it prints are computed over cases
   SELECTED for disagreement, so they are artefacts of that selection (the A-B kappa is
   negative by construction). They must never be quoted as agreement rates. Only the
   settled/split counts are meaningful there.

## Getting the cases

The 351 mined cases are NOT in this repository and will not be. They are verbatim
turns from real working sessions, carrying project paths, branch names and working
directories, and 35 of them concern enterprise/partnership work. This repository is
public.

This is a declared limitation of the measurement, not a formality: **a third party
cannot currently replay the numbers above, only the method.** Any scorecard built on
this protocol must say so.

To replay with the same cases, one of these has to happen first, and it is the
repository owner's call:

- **Same machine.** The labellers read the case files directly from the local gold-set
  directory. No transfer, nothing to publish. Simplest option when the labelling tool
  runs locally.
- **Private gold-set repository.** The cases move to a private repo and labellers are
  granted access there. Keeps provenance intact and makes the measurement replayable
  by anyone with access.
- **Redacted public set.** Sensitive cases are dropped or scrubbed. Cheapest to share
  and the worst methodologically: removing 35 of 351 cases changes the distribution
  being measured, so the resulting figures are no longer comparable to the ones above
  unless the removal is itself reported.

Mining a fresh corpus from your own transcripts needs none of the above, and answers
the cross-family question just as well — the confound is about raters, not cases.
