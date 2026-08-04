# Labelling prompt — Phase 0 gold set (FROZEN 2026-08-04, before batch 3 was read)

This is the exact instruction handed to every labeller. It is identical for A, B and C;
only the model and the input/output paths differ. Archived so the labelling pass is
replayable — batches 1 and 2 ran on a prompt reconstructed at the time and NOT archived,
which is a declared reproducibility gap for those 120 cases.

---

You are labelling real turns from software-engineering sessions for a routing benchmark.

Read `~/.claude/goa-phase0/label-rubric.md` FIRST, in full, before opening any case.
It is frozen: do not reinterpret it, do not add shapes, do not merge shapes.

Read your assigned case file: `<CASES_PATH>`. It is JSONL, one case per line, each with
`case_id` and `text`.

For EACH case, emit exactly one JSONL line to `<OUT_PATH>`:

    {"case_id": "<verbatim from input>", "label": "<one of the 15 shape names, or none>", "confidence": "low|medium|high", "rationale": "<one sentence, under 120 chars>"}

Binding constraints:

1. **One label per case.** Never two, never a list. If two shapes fit, pick the one
   matching the case's PRIMARY question — what the author is blocked on — not a
   secondary aspect mentioned in passing (rubric rule 2).
2. **`none` is a real answer, not a failure.** Most real turns state no routable
   problem: acknowledgements, status reports, pure execution orders ("push the branch"),
   pasted material that is not the author's own problem. Label them `none`. Do NOT
   stretch a turn onto the nearest shape to avoid answering `none`.
3. **Judge the case as written** (rubric rule 3). Do not infer intent from the project
   it came from, from its `cwd`, or from what you know about this codebase.
4. **Report low confidence honestly** (rubric rule 4). Low confidence is the signal the
   adjudication pass reads. A false `high` corrupts the measurement it feeds.
5. **Blind pass.** Do NOT read, open, list, or grep any other `labels-*.jsonl` file in
   `~/.claude/goa-phase0/`. You must not know what any other labeller answered. If you
   find yourself about to look, stop: that read destroys the inter-rater measurement
   this whole exercise exists to produce.
6. **Cover every case, in input order.** Your output must have exactly as many lines as
   your input, one per `case_id`, no reordering, no skips, no duplicates.
7. `rationale` states WHY that label — never restate the case text, never hedge with
   "possibly/maybe this could be".

Emit nothing but the JSONL file. Your final message is a single line:
`<n> cases labelled -> <OUT_PATH>`.
