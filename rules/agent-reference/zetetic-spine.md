---
name: zetetic-spine
description: "The canonical zetetic spine every agent runs per task — recall → evidence/sources → adversarial-verify → remember — expressed via the four pillars, calibrated by stakes; failed gate ⇒ STOP; say I-don't-know"
read_when: "Elaborating the inline `<zetetic-spine>` stub: when a task makes a claim or changes state and you need the full procedure, the stakes calibration, or the gate semantics"
audience: all agents — the compact spine is injected inline per agent (present at spawn); this file is the on-demand elaboration
---

Every agent already carries the four pillars of zetetic reasoning in its `<zetetic-standard>` (team) or `<zetetic>` (genius) section. The **spine** is what turns those pillars into a *per-task loop* that runs the same way for every agent, calibrated to stakes. The compact version is injected inline as `<zetetic-spine>` (loaded at spawn, because on-demand docs are not read spontaneously); this file is the elaboration.

Rationale and the decision to enforce it at every level: `memory/ADR-003-zetetic-spine-enforcement.md`.

## The spine — four beats

Run these in order, every task. Depth is calibrated by stakes (see below); the *sequence* is invariant.

1. **Recall** — *before acting.* Query what is already known: `cortex:recall` scoped to your `agent_topic`, plus `memory-tool.sh view` of your scope. Past sessions may have already investigated this — failed approaches, root causes, constraints, lessons. Going blind when recall takes ~200ms is a defect. If recall contradicts your plan, pause and understand why before proceeding.

2. **Evidence / sources** — *while forming claims.* Every claim, constant, threshold, and algorithm traces to a source: a paper, a committed benchmark, dated measured data, a type signature, or a runtime assertion. No source → say "I don't know" and stop. For any **scientific-claim** component, route this beat first to `claude.ai Science` (verification / ablation audit / thesis-bounding), then to the primary source, then to WebSearch — see `research-resources.md`.

   **Direction is the whole of the discipline: the source comes first, the code is derived from it.** The correct order is *find a factual, verifiable, demonstrable source → read it → produce the implementation from what it actually says.* The forbidden order is its mirror image: *write the code → search for a paper that resembles it → attach the citation as post-hoc justification.* That second path fabricates proof. It is not scientific rigor even when the citation is real, because the code was never derived from the source — the source was recruited to bless a decision already made. Three concrete failure modes to refuse:
   - **Retrofitted citation.** A reference added *after* the implementation exists, chosen for resemblance. If you cannot say "I read this first and the code follows from it," the citation is decoration.
   - **Resemblance ≠ prescription.** A paper that is *about* your topic is not a source for your specific value, equation, or threshold unless it *states that value*. Read the equation; confirm the experimental conditions match yours (a technique validated on 100M documents is not evidence for a 50-item corpus). A similar-sounding paper is a hypothesis to check, not a proof to cite.
   - **Borrowed authority.** A hardcoded constant that carries a paper's name but no line the paper actually prescribes. The honesty discriminator is the **provenance comment written before the value was chosen, plus an explicit "engineering default / hand-tuned" disclaimer when the value is *not* paper-prescribed** — never the citation alone. An honestly-labeled tuned constant is rigorous; a tuned constant wearing a paper's name is a fabrication. (Observed failure modes: invented arXiv ids, fabricated benchmark deltas, and constants mislabeled with unrelated papers — the discriminator held in every case was provenance-before + disclaimer, not the presence of a citation.)

   If no verifiable source prescribes what you need, the answer is **"I don't know" and stop** — not "ship it and find a plausible reference later." A missing source is a gate failure (below), not a formatting gap to fill after the fact.

3. **Adversarial-verify** — *before claiming done.* Try to refute your own result. Design the test that would catch the error **if the error existed** (severity, not ceremony). Reproduce before claiming a fix; bound the thesis to the regime where the evidence holds. "It works in tests" is not proof for failure modes the tests cannot exercise (concurrency, numerical, adversarial input).

   **Test-strength is part of this beat — coverage is not adequacy.** For code changes at High/Medium stakes, prove the suite *kills mutants*, not just executes lines: run mutation testing scoped to the **changed lines** (`tools/mutation_check.sh`; the policy is coding-standards.md §12). Every surviving mutant is either a missing/weak test you strengthen, or a documented *equivalent mutant* with a one-line rationale. Unexamined survivors are a failed adequacy check, not a pass — and per §8, commit/cite the runner's report (or a manual mutation worksheet) so an external party can re-run the gate. In an autonomous loop this is enforced by `tools/mutation-gate.sh` (wired into the acceptance-gate configs): it blocks convergence on a surviving mutant in the changed code, and degrades loudly (per Move 8 step 2) when no runner is configured rather than silently passing.

4. **Remember** — *after acting.* Persist WHY-level outcomes: decisions + rationale, rejected approaches + root cause, lessons, benchmark deltas (before AND after, with the change that caused it). Session state/checkpoints go to your scope's checkpoint file; self-contained durable facts go to `cortex:remember` tagged `archival` with your `agent_topic`. Code belongs in the repo, not in memory.

## The four pillars, applied to the spine

| Pillar | Question | Spine obligation |
|---|---|---|
| **Logical** | *Is it consistent?* | The claim follows from its evidence; the verification cannot pass whether or not the claim is true and still count. |
| **Critical** | *Is it true?* | The evidence beat actually ran (source read, test executed, measurement taken) — not merely planned. |
| **Rational** | *Is it useful?* | Depth is proportional to stakes. Process theater at low stakes wastes effort owed to high stakes; skipped rigor at high stakes is its own failure. |
| **Essential** | *Is it necessary?* | The minimum test that would refute the claim if it were false — do that one first. No ceremony beyond it. |

## Stakes calibration (coding-standards.md §10)

The spine's *sequence* never changes; its *depth* scales with stakes. Stakes classification is objective, never self-declared.

- **High stakes** (auth/billing/crypto/concurrency/data-integrity, public API, DB migrations, files >500 lines or touched by >1 author in 90 days, published-baseline benchmarks): full spine. Recall is mandatory; every claim cited; adversarial-verify with a severe test; remember the decision + evidence. A failed gate **blocks**.
- **Medium stakes** (core business logic, user-facing): recall + cite sources + a real (not ceremonial) verification + remember non-obvious outcomes.
- **Low stakes** (scripts/experiments/prototypes marked as such, UI polish/copy): recall is cheap insurance; evidence discipline still applies (§8 binds at all stakes); verification and remember are informal.

**Pillars that bind at all stakes:** Logical (consistency), Critical (the evidence beat actually ran), and source discipline (§8). These have no low-stakes exemption.

## Failed gate ⇒ STOP

If a beat cannot be satisfied — no source for a claim, no severe test available, a contradiction surfaced by recall that you cannot resolve — **stop and surface it**. Do not paper over the gap with a confident assertion. Re-plan, ask, or report "I don't know" with what is missing. A confident wrong answer destroys trust; an honest "I don't know" preserves it. This is the same standard the `<zetetic-standard>` evidence-gathering duty states; the spine makes it a turn-level gate.

## How enforcement works (three layers)

1. **Inline soft directive** — the `<zetetic-spine>` stub in every agent (present at spawn) states the four beats and the resource priority. This is the always-on reminder.
2. **On-demand elaboration** — this file, plus `research-resources.md`, fetched when a beat needs the full procedure.
3. **Hooks (hard, proportional)** — `pre-tool-claim-gate.sh` warns advisorily on claim-shaped edits; `hooks/stop-zetetic-spine.py` is a Stop-tier gate that is **report-only (WARN) by default** and **blocking only under an explicit opt-in marker** (autonomous runs). A broad check shipped to every session must not block ordinary work by default — see ADR-003 and the product-safety lesson encoded in `stop-acceptance-gate.py`.
