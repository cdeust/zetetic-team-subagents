# Labelling rubric: Phase 0 gold set (FROZEN before any case was read)

The block below is the frozen rubric, quoted verbatim. Every labeller read it in
full before opening a case. It is byte-for-byte what they were given and must not
be edited, including its punctuation. House copy rules apply to this file's prose,
not to quoted evidence.

```
# Labelling rubric — Phase 0 gold set (FROZEN before any case was read)

Assign to each case EXACTLY ONE label: one of the 15 shape names below, or `none`.

Rules:
1. `none` when the turn states no routable problem: an acknowledgement, a status report,
   a pure execution order ("push the branch"), pasted material that is not the author's own
   problem, or a machine-injected turn that survived filtering.
2. One label only. If two shapes fit, pick the one matching the case's PRIMARY question —
   what the author is actually blocked on — not a secondary aspect they mention in passing.
3. Judge the case as written. Do not infer context from the project it came from.
4. Low confidence is information, not failure: report it. It is what the adjudication pass reads.

The descriptions below are copied verbatim from each skill's `description:` frontmatter,
which is exactly what the router sees. Nothing has been paraphrased or added.

## `boundary-design`

Draw the line where it costs least. Use for build-vs-buy calls, "where does this module/team/service boundary belong?", APIs and abstractions forcing users into implementation vocabulary, tools that should augment rather than automate, hardcoded decisions that belong at runtime, or information nobody can find.

## `causal-audit`

Correlation walked in; make it prove causation. Use when someone claims "X causes Y" from observational data, asks "did the change actually cause the improvement?", "is this confounded?", "what would have happened if we hadn't shipped it?", plans an A/B test, or investigates why an incident/outbreak spread the way it did.

## `decision-bias-check`

Audit the decision before it ships. Use for "are we sure about this?", high-stakes choices made on fast intuition, plans with no failure scenario, estimates that are suspiciously optimistic, metrics being gamed (Goodhart), unfalsifiable claims, negotiation prep, or strategies that break in extreme conditions.

## `estimation`

Bound it before you build it. Use when a decision is blocked by "we don't have data", an estimate looks suspiciously precise, someone asks "is this even feasible?", "how much capacity do we need?", "will this scale?", or a claimed number has never been cross-checked by a second method.

## `evidence-synthesis`

Turn a pile of sources into a defensible claim. Use for "what does the literature actually say?", conflicting studies or benchmarks, "is this result trustworthy?", arguments that need claim-evidence-warrant structure, qualitative data needing coding, or a theory with no catalog of its own contradicting evidence.

## `experience-and-transmission`

The artifact is correct and nobody can use, learn, or read it. Use when every component metric is green but the end-to-end experience is broken, when onboarding is too slow or documentation goes unread, when the observer is inside the system being studied (UX research, dogfooding), or when code is right but unreadable by the next maintainer.

## `failure-forensics`

Read the wreckage before rebuilding. Use for incident post-mortems, "what happens when everything goes wrong at once?", flaky or anomalous cases being filtered out as noise, "that's weird" moments nobody wrote down, oscillating or unstable feedback behavior, and designs whose only failure mode is crash.

## `formal-correctness`

Prove it, don't test-and-hope. Use for concurrent or distributed code with no written spec, "how do we know this is correct?", interfaces that break when implementations are swapped, correctness argued by walking through example traces, wall-clock time used for ordering, or "can this be decided at all?".

## `measurement-discipline`

Fix the instrument before trusting the number. Use when someone says "the metric improved but I don't trust it", "measured more than the parts predict", "we want to improve X but nothing reads X", "the numbers don't add up", "requests/money/time are disappearing", or a measurement may perturb the system it measures.

## `narrative-sensemaking`

Some questions are "what happened and what did it mean", not "what is the mechanism". Use when an account must be reconstructed rather than measured, when a sequential process has a missing or out-of-order step, when a story is told to explain a failure, or when a claim sounds authoritative but may be structurally impossible before any source is even checked.

## `normative-design`

Legitimacy is a design property, not an afterthought. Use when a rule, policy, or allocation must be written or applied and the open question is "is this fair and consistently applied?" rather than "does it work", when a general rule does not determine a specific case, when harm emerged with nobody having decided it, or when "we've always done it this way" is the only justification on offer.

## `problem-reframing`

The question itself may be the bug. Use when a debate goes in circles, both options of a binary feel wrong, improving one parameter degrades another, "we're stuck" on a problem that resists direct attack, a metaphor is doing hidden work in the architecture, or a trade-off is being denied rather than made.

## `representation-and-possibility`

When the notation is the obstacle and the option space was never enumerated. Use when the current vocabulary hides the solution, when a system claims to be exhaustive but nobody checked whether the space is searchable, when a forecast is too narrow because no one pushed the principle to its limit, or when you need the answer now and the proof afterwards.

## `structure-discovery`

Find the hidden pattern that organizes the mess. Use for "these look related but we can't say how", classification with suspicious gaps, reverse-engineering an undocumented system or format, "is there a symmetry we're not using?", scale-free or fat-tailed data, or generating conjectures from computed special cases.

## `systems-leverage`

Find where a small push changes the whole system. Use when local fixes keep failing, "where should we intervene?", recurring organizational patterns (shifting the burden, escalation, tragedy of the commons), behavior driven by stocks/flows/delays, adoption stalling, or shared resources being depleted.

## `none`

No routable problem stated (see rule 1).
```
