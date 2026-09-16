---
name: redaction
description: >
  The house redaction pass: edit or audit prose against the ai-architect.tools
  pattern inventory of AI-writing tells, with a falsifiable eval and a detect
  mode that returns quoted-line evidence per pattern, never an "AI probability"
  score. Successor to the original redaction agents; the inventory is owned and
  refined in-tree.
category: writing
trigger: >
  Before publishing any outward-facing prose — LinkedIn posts, READMEs, release notes,
  issue bodies on public repos, marketing copy, documentation. Also when asked whether a
  text "reads as AI".
agents:
  - feynman
shapes: []
input: A draft (any format), plus optionally a sample of the author's own writing for voice calibration.
output: Edited draft with a "What changed" section (edit mode), or a findings report quoting each offending line with its pattern name and fix (detect mode).
zetetic_gate:
  logical: "Every flagged line names a specific pattern from the inventory below — no vibes-based 'sounds like AI'"
  critical: "Detect mode quotes the actual line; named patterns are evidence the author can check — AI detectors guess, this skill does not"
  rational: "Minimum effective edit: cutting proportional to actual slop; a rough draft with a real voice must survive as the same voice"
  essential: "No fact, number, citation, or claim may be invented by the edit — weasel attribution is resolved by naming the source or cutting the claim (coding-standards §8)"
composes: [citation-verifier]
aliases: [no-slop, ai-tells, deslop]
hand_off: {}
---

## Purpose

The redaction pass is a first-party capability of the ai-architect.tools
ecosystem: one pattern inventory, owned in this tree, applied wherever our
products surface prose (agents here, Cortex wiki/narrative generation,
eventually cortex-viz panel text), and refined from our own published copy as
we work. It descends from the original redaction agents (2026) that enforced
the first three house rules.

**Sources consulted** (zetetic §8 — the inventory is informed by these, and
diffed against them on the review cadence; the capability and its method are
ours):
- Wikipedia, "Signs of AI writing" (WikiProject AI Cleanup) — the primary
  maintained catalog of the patterns.
- Prior art on enforcement method: blader/humanizer v2.9.1 and
  petergyang/no-ai-slop (both MIT) — pattern-inventory editing with voice
  preservation, and the separate pass/fail eval + quoted-evidence detect mode,
  respectively. Our implementation is house-written.

## Modes

**Edit (default).** Minimum effective edit. Identify the core point and 3-5 voice signals
first (vocabulary, cadence, bluntness, humor, uncertainty); preserve them. Return the
edited draft plus a short What changed section. Never invent facts, names, numbers,
quotes, or citations not in the source; swapping vague for specific is allowed only when
the specific comes from the source or the author.

**Detect.** Name each pattern found, quote the line, give the fix in a few words. Do not
rewrite, do not score, do not guess whether AI wrote it. Offer the edit afterwards.

**Voice calibration.** If the author provides a writing sample, its habits outrank this
inventory — except the HOUSE DELTAS, which are absolute for our own published copy.

## Pattern inventory

### Content
1. **Importance puffery** — "stands as a testament", "pivotal moment", "vital role", "underscores its significance", "evolving landscape", "indelible mark". State the fact; let the reader judge.
2. **Notability padding** — lists of media mentions, "active social media presence". Keep the one cited item with real context.
3. **Superficial -ing analysis** — trailing "highlighting/underscoring/reflecting/showcasing/fostering…" clauses that fake depth. Replace with the concrete mechanism or cut.
4. **Promotional language** — "boasts", "vibrant", "rich heritage", "nestled", "breathtaking", "renowned", "stunning", "groundbreaking". Neutral statement instead.
5. **Weasel attribution** — "experts agree", "industry reports", "studies show", "widely regarded". **House rule: this is a coding-standards §8 violation in prose** — name the source or cut the claim; never decorate an unsupported claim.
6. **Outline-shaped filler sections** — "Challenges and Future Prospects" and kin, written to fill a template rather than say something.

### Language and grammar
7. **AI vocabulary** — banned outright: delve, foster, leverage, utilize, facilitate, empower, streamline, robust, cutting-edge, paradigm shift, game changer, tapestry, realm, beacon, multifaceted, meticulous, intricate, paramount, transformative, elevate, embark, supercharge, harness, ever-evolving.
8. **Copula avoidance** — "serves as a hub" → "is"; "functions as" → "is". Prefer is/has when clearer.
9. **Negative parallelism** — "It's not X. It's Y." / "Not a X. Not a Y. A Z." State Y directly. (House: antithesis ban, absolute in copy.)
10. **Rule of three** — triads used as rhythm crutch. (House: triad ban, absolute in copy.)
11. **Synonym cycling** — the agent → the assistant → the tool. Repeat the clear word.
12. **False ranges** — "from X to Y" spans that measure nothing.
13. **Passive voice / subjectless fragments** — restore the human subject and the direct verb.

### Style
14. **Em dashes** — **House rule, stricter than both upstreams: zero em dashes in published copy.** No exception for long drafts.
15. **Decorative boldface** — bold mid-sentence for emphasis. Format follows content.
16. **Inline-header vertical lists** — bullets where two sentences of prose read better.
17. **Title Case Headings** — sentence case.
18. **Emojis** in headings or as decoration.
19. **Curly quotes** inconsistency — pick one convention.

### Communication artifacts
20. **Collaborative leftovers** — "I hope this helps", "Let me know if", "Certainly!".
21. **Knowledge-cutoff disclaimers** and speculative gap-filling.
22. **Sycophancy** — "great question", servile hedging.

### Filler and endings
23. **Filler phrases** — "it's worth noting", "at the end of the day", "in today's world", "when it comes to", "in order to", "let's dive in".
24. **Excessive hedging** — stacked qualifiers that carry no real uncertainty. Keep hedges expressing genuine doubt.
25. **Generic positive conclusions** — "exciting times ahead". Cut.
26. **Hyphenated-pair overuse** — "fast-paced, ever-changing".
27. **Persuasive authority tropes** — rhetorical questions as fake engagement.
28. **Signposting** — "In this section we will…". The reader is already here.
29. **Fragmented headers** over two-sentence sections.
30. **Throat-clearing openers** — "Here's the thing", "Let me be clear", "The uncomfortable truth is".
31. **Faux-insight setups** — "What nobody tells you", "The part everyone misses". Make the claim stand alone.
32. **Colon reveals** — "The best part: it learns." Plain sentence instead; colons are for lists, labels, quotes.
33. **Fake-profound kickers** — the mic-drop final metaphor. Delete it; end on the last concrete point. Do not rewrite it into a better metaphor.
34. **Summary-recap endings** — "In conclusion", "Ultimately", a final paragraph restating the piece.
35. **Manufactured punchlines / staccato drama** — "That's it. That's the whole thing."
36. **Aphorism formulas** — quotable-shaped closers that say nothing testable.

## HOUSE DELTAS (absolute for our published copy; override voice samples)

- **Zero em dashes.** (§14 upstream allows 1-2 in long drafts; we do not.)
- **No antithesis / binary contrasts** (§9) and **no triads** (§10) in copy, ever.
- **Weasel attribution = §8 violation**: named source or cut (§5).
- **LinkedIn formula** (proven on the Cortex build-in-public post): value proposition first,
  falsifiable numbers, named papers, ecosystem hashtags. A post that cannot cite a number
  or a source gets rewritten until it can, or does not ship.

## Eval (run on your own edit before returning it; all must pass)

1. Every claim in the original survives; nothing invented.
2. The writer would recognize the edited draft as their own voice.
3. Zero em dashes, zero antithesis constructions, zero triads (house copy).
4. Every remaining attribution names its source.
5. Cutting proportional to actual slop; strong human sentences untouched.
6. Ends on a concrete point, takeaway, or next action; no recap, no kicker.
7. Detect-mode output quotes each line and names each pattern; no score, no rewrite.

## Review cadence

The inventory is owned here, not a dependency. On each significant writing session, note
patterns that slipped through; diff against upstream (`blader/humanizer` releases,
`petergyang/no-ai-slop`) quarterly and fold in what we lack. Log refinements below.

- 2026-07-24 — initial inventory (house deltas + 36 patterns synthesized from the sources above).
