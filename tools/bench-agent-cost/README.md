# bench-agent-cost -- paired cost/quality benchmark (Phase 3)

Phase 3 of `/Users/cdeust/.claude/plans/staged-rolling-shannon.md`: the
pre-registered, replicated, blind-scored measurement infrastructure Phase 4
(a `ux-designer` pilot) and Phase 7 (rollout) need before either can proceed
on evidence rather than assumption. This document is the **pre-registration
artifact** (Fisher discipline, Move 1/2): everything below was frozen before
any run's results existed, and every subsequent run is judged against it,
not the reverse.

## Motivating goal, and the hard line around it

This benchmark exists because the initiative's stated goal is reducing
token/compute usage in agent-to-skill migration. **That goal never becomes
a green-software or carbon claim in this document or in any report this
tool produces.** A domain-expert green-software consult was run before
this benchmark was designed; its conclusions are incorporated verbatim
below, not re-derived or softened.

### 1. Tokens and wall-clock are operational-cost proxies, never a carbon claim

Every number this tool reports -- token counts, wall-clock duration,
CLI-reported dollar cost -- is an **operational-cost proxy**, not an energy
or carbon figure. Tokens and wall-clock correlate with energy only under
constant conditions (model, hardware generation, batching, datacenter grid
mix) that are not observable or controlled from a client calling a
black-box API. A fixed tokens-to-CO2 conversion factor is unfounded: energy
depends jointly on context length, output length, model, and batching
(Vellaisamy et al. 2026, arXiv:2608.28044). Every results section in this
tool's output uses "operational-cost proxy" / "compute-proxy" language. The
phrase "green software engineering" may appear only as the motivating goal
in prose like this paragraph -- never attached to a measured number.

### 2. SCI disclaimer

Per the Software Carbon Intensity (SCI) specification's framing for
Agentic AI (per-Workflow-Execution functional unit): this benchmark defines
**R** (the functional unit) as one completed task (one paired
replication's worth of work, scored against its rubric). It does **not**
measure, and cannot measure from this vantage point, **E** (energy
consumed), **I** (grid carbon intensity), or **M** (embodied carbon of the
hardware). There is no GPU telemetry available to a CLI client, no
visibility into which datacenter or hardware generation served a given
call, and no fleet-level embodied-carbon data. The SCI spec requires E, I,
and M to be measured consistently between a baseline and a variant before a
carbon comparison is valid; this benchmark cannot satisfy that requirement
and does not attempt to. Every SCI-adjacent artifact this tool produces
carries this paragraph or a pointer to it.

### 3. GSF principles cited for mechanism/methodology only

- **Energy Proportionality / Caching** -- explains *why* tokens move between
 conditions, not what it costs in carbon: an inline skill inherits the
 calling session's already-warm context (cache-read tokens dominate); a
 subagent spawn pays a cold-start cost (fresh system prompt, fresh tool
 schemas, a cache miss). This is the mechanism the paired design is built
 to isolate -- it is never treated as evidence of carbon impact.
- **Networking** -- token payload size is used as an imperfect but legitimate
 proxy for data moved per call, nothing more.
- **Measurement & Optimization** -- governs the whole methodology: measure
 first, replicate (≥5 seeds), randomize execution order, keep a
 provenance sidecar per run.

### 4. Explicitly out of scope

- **Carbon Intensity / Demand Shaping** -- this is synchronous interactive
 developer work; it is not schedulable or shiftable against grid
 conditions, so demand-shaping has no application here.
- **Embodied Carbon** -- choosing inline-skill vs. subagent-spawn does not
 change hardware provisioning, and this benchmark has no visibility into
 fleet composition to even gesture at an embodied-carbon estimate.

### 5. The direction of the result is not assumed

A subagent spawn can, in principle, be **cheaper** than inlining into an
already-large calling session's context: a cold subagent context can be
smaller than the caller's accumulated conversation history that an inline
skill would otherwise carry forward. This is a real possible outcome, not
a strawman. Nothing in `run_benchmark.py`, `score_quality.py`, or
`analyze_results.py` assumes a direction -- the paired measurements decide
it, and `analyze_results.py` reports whichever condition wins per metric
without a thumb on the scale.

## Pre-registration

**Hypothesis (per task, tested independently for each of the 3 tasks):**
Inlining a skill's procedure into the calling session (`inline_skill`)
does not increase total operational-cost-proxy tokens relative to spawning
the task's primary named subagent (`subagent_spawn`) by more than can be
explained by chance, AND does not reduce blind-scored quality by more than
the pre-registered non-inferiority margin (see below), at matched model,
effort, and tool grant.

**Baseline:** `subagent_spawn` -- full dispatch via the Agent tool to the
task's `primary_agent`, exactly as it runs in production today.

**Method:** paired sessions, same exact model (`--model`), same effort
(`--effort`), same tool grant (`Read,Agent,Glob,Grep` for both conditions -- 
see "Why Agent is granted to both conditions" below), same git snapshot
(the worktree's `HEAD`), same fixture file. Only the prompt's stated
representation changes: "perform this yourself, do not delegate" vs. "use
the Agent tool to delegate to `<primary_agent>`, do not perform it
yourself."

**Why `Agent` is granted to both conditions, not withheld from
`inline_skill`:** the protocol's constraint is "only the representation
changes." If the inline condition's tool grant omitted `Agent`, the
manipulation would be confounded with a capability difference, not a pure
representation difference. Instead, both conditions hold identical tool
grants, and `inline_skill` is defined by an *instruction* not to delegate.
`usage.condition_matches_representation` (`lib/usage.py`) checks
`subagent_stats.spawned` from the CLI's own usage JSON to verify the
instruction was actually followed; a run where it wasn't is discarded at
analysis, not silently counted (Fisher: a manipulation that didn't take is
not data).

**Data splits:** none -- this is not a train/test-split benchmark. The
"split" analog is the fixed task corpus (3 tasks, frozen fixture files
under `fixtures/`, committed to this PR) and the fixed rubric per task
(`tasks/*.json`, committed).

**Analysis plan:**
- Primary compute-proxy metric: total tokens (`input + output +
 cache_creation + cache_read`), paired two-tailed t-test, α = 0.05
 (`lib/stats.paired_comparison`).
- Secondary compute-proxy metrics: wall-clock `duration_ms`,
 CLI-reported `total_cost_usd` (same paired test).
- Quality metric: mean of two blind evaluators' rubric scores per run,
 paired one-sided non-inferiority test against the margin below
 (`lib/stats.non_inferiority_verdict`).
- Minimum 5 paired replications per task, seeds/order fixed by
 `--seed` before any run (`random.Random(seed).shuffle(order)` per
 replication -- Fisher: randomize execution order so cluster drift or
 cache warm-up does not alias with condition).
- Stopping rule: exactly 5 replications per task, run to completion
 regardless of the first replication's outcome. No early stopping on a
 favorable early result (Move 1: the stopping rule is decided, not
 discovered).
- Tie-breaking: a seed-level tie (`wins_a == wins_b` per
 `PairedComparison`) is reported as a tie, not resolved in either
 direction.

**Non-inferiority margin:** the skill condition's mean blind quality score
must not fall more than **1.0 point below** the subagent condition's mean,
on each task's 10-point rubric (10%). Rationale (reasoned choice, not a
sourced empirical constant for this exact rubric -- flagged honestly per
§8 rather than dressed up as a citation): a 10-point rubric scored by two
evaluators has an irreducible inter-rater disagreement band; published
LLM-judge/human agreement studies on comparably-scaled technical rubrics
report agreement in the 80-85% range (Zheng et al. 2023,
arXiv:2306.05685, MT-Bench), which is consistent with a ±0.5-1.0 point
band of noise on a 10-point scale. Setting the margin at 1.0 keeps the
test from declaring a real regression "non-inferior" while not demanding
resolution finer than the scoring method can reliably provide. This
margin is fixed **before** any run in this repository's history and is
not adjusted after seeing results (coding-standards.md §8, Move 1).

**p-hacking disclosure:** the three metrics above (tokens, wall-clock,
cost) and the quality non-inferiority test are the full set of
confirmatory analyses. Any breakdown by evaluator, by rubric sub-criterion,
or by order-position is exploratory and must be labeled as such in any
report -- it was not decided before data existed.

## Task corpus

Three tasks, each pairing an already-skill-fronted `skills/engineering/*.md`
with the same skill's primary named subagent (`rules/agent-vs-skill-
classification.md`'s worked table), each with a self-contained synthetic
fixture (never live production code, so a run never touches this repo's
own source as a side effect):

| Task | Skill | Primary agent | Fixture |
|---|---|---|---|
| `review_small_diff` | `skills/engineering/review.md` | `code-reviewer` | `fixtures/review_target.py` -- 3 planted violations |
| `test_small_module` | `skills/engineering/test.md` | `test-engineer` | `fixtures/test_target.py` -- pure function with edge cases |
| `debug_small_bug` | `skills/engineering/debug.md` | `engineer` | `fixtures/debug_target.py` -- root cause one layer removed from the symptom |

Each task's full rubric (points per criterion) is committed at
`tasks/<task_id>.json` and frozen before any run.

Note on `review_small_diff`: `skills/engineering/review.md`'s own
`agents:` frontmatter names both `code-reviewer` (sonnet) and `architect`
(opus); `tools/skill-runner.sh` prints its own model-tier escalation
banner for `architect` when the skill's procedure is fetched. This
benchmark's `code_reviewer`-only scope does not silence that banner -- the
inline condition's prompt is built from the *unedited* output of
`tools/skill-runner.sh review`, banner included, because a real inline
invocation would show a calling session exactly that text. This is a real
tension the tool surfaces rather than launders: an honest inline
representation for a skill naming a mixed-tier agent list necessarily
carries its own escalation warning.

## Evaluator limitation (must be repeated in any report using `score_quality.py`)

`score_quality.py`'s two "evaluators" are two differently configured
`claude -p` judge calls (different model tier, different prompt phrasing),
not trained human reviewers. This is a real limitation, not a footnote to
skip: LLM-as-judge agreement with human preference is measured, not
perfect -- Zheng et al. 2023 report ~80-85% agreement with human raters on
MT-Bench. This tool uses LLM judges because no human evaluator labor is
available in its execution context, and states plainly that its quality
comparison carries less evidentiary weight than the human-blind-review
standard Move 5 of the experiment-runner procedure calls for. A production
decision (Phase 4, Phase 7) that leans on the quality axis should
re-score a sample with human reviewers before treating non-inferiority as
established.

## Reproducibility manifest -- provenance sidecar schema

Every run under `docs/bench-agent-cost/<date>/raw/*.json` carries
(`lib/provenance.build_sidecar`):

```json
{
 "task_id": "...", "condition": "inline_skill|subagent_spawn",
 "replication": 1, "order_position": "first|second",
 "code_hash": "<git HEAD sha>", "code_dirty": false,
 "prompt_hash": "<sha256 of the exact prompt sent>",
 "cli_version": "<claude --version output>",
 "model": "...", "effort": "...", "rng_seed_for_order": 20260905,
 "environment": {"platform": "...", "python_version": "..."}
}
```

alongside `usage_raw` (the CLI's own `usage`/`total_cost_usd`/
`duration_ms`/`duration_api_ms`/`num_turns`/`subagent_stats.spawned`
fields, extracted verbatim by `lib/usage.extract_usage` -- never re-derived
or estimated) and `representation_check_passed`. `build_sidecar` refuses
to run against a dirty worktree unless explicitly overridden, per Move 3:
a run recorded against an unreproducible code state is not a run this
benchmark reports.

Raw usage is kept in its own field, separate from any derived figure
(e.g. a future re-pricing of the same token counts under a different rate
card) -- Move 3: "raw usage data ... kept separate from any derived cost
figure ... so the primary data isn't polluted by a pricing assumption that
changes later." `total_cost_usd` here is the CLI's own contemporaneous
pricing at time of the call, recorded as-is; it is not this tool's
invented number.

## Running it

```bash
# 1. Run the paired benchmark for one task, 5 replications, both conditions.
tools/bench-agent-cost/run_benchmark.py \
 --task tools/bench-agent-cost/tasks/review_small_diff.json \
 --replications 5 --model haiku --effort low \
 --out-dir docs/bench-agent-cost/20260905 --repo-root .

# 2. Blind-score every run's output against the task's rubric.
tools/bench-agent-cost/score_quality.py \
 --raw-dir docs/bench-agent-cost/20260905/raw \
 --task tools/bench-agent-cost/tasks/review_small_diff.json \
 --out-dir docs/bench-agent-cost/20260905/scored --repo-root .

# 3. Analyze: paired stats + the pre-registered non-inferiority verdict.
tools/bench-agent-cost/analyze_results.py \
 --raw-dir docs/bench-agent-cost/20260905/raw \
 --scored-dir docs/bench-agent-cost/20260905/scored \
 --task tools/bench-agent-cost/tasks/review_small_diff.json \
 --non-inferiority-margin 1.0
```

`--model haiku --effort low` above is a **cost-bounded smoke/gate run**,
distinct from the frozen production protocol (default `--model sonnet
--effort medium`, matching this repo's own sonnet baseline per
`rules/agent-vs-skill-classification.md`). The smoke run exists to prove
the tool's plumbing end to end (Move 1: "smoke tests on a tiny subset
are allowed pre-freeze; full runs are not") -- its numbers are not a claim
about representative production cost or quality at the sonnet tier, and
must not be cited as such. A Phase 4/7 decision requires re-running at the
pinned production model/effort.

## Negative-result log

**2026-09-05, `review_small_diff`, haiku/low smoke run (n=5, single task) --
non-inferiority NOT established.** Raw results at
`docs/bench-agent-cost/20260905/`. This is the cost-bounded smoke run
described above, not the frozen sonnet/medium production protocol -- logged
anyway per Move 7, since it is a completed run whose result did not
support the hypothesis and a null/negative result is never quietly dropped
for being "just a smoke run."

- Quality: inline_skill mean 8.90/10, subagent_spawn mean 9.20/10 (2 blind
  evaluators). Paired one-sided non-inferiority test at margin=1.0:
  lower 95% confidence bound on the difference = -1.166, which is below
  -1.0 -> **`non_inferior_at_05: false`**. At n=5 this is underpowered to
  distinguish "genuinely inferior" from "noise wider than the margin";
  it is reported as inconclusive, not as evidence the inline condition is
  worse. Seed-level: 2/5 inline wins, 2/5 subagent wins, 1 tie -- no
  consistent direction.
- Total tokens: inline_skill mean 216,824 vs. subagent_spawn mean 111,222
  (paired t=134.5, df=4, significant at 0.05, inline wins 0/5 seeds on this
  metric -- i.e. subagent used fewer tokens on every replication). This
  is the opposite of the initiative's presumed direction and is exactly
  the "subagent can be cheaper" case flagged as a real possible outcome
  in constraint 5 above, not a strawman: `skills/engineering/review.md`'s
  procedure text itself (~2,600 words, plus the escalation banner) is
  inlined into every `inline_skill` prompt, while `subagent_spawn`'s
  cold subagent context did not carry that same procedure text into the
  measured session's own token count (it is spent inside the spawned
  subagent's separate context, which this benchmark's top-level `usage`
  JSON reports as the whole session's total including the subagent's
  cost -- see the divergence with total_cost_usd below, which suggests
  the aggregation is not as simple as "subagent costs are hidden").
- total_cost_usd: inline_skill mean $0.21 vs. subagent_spawn mean $0.47 --
  **the opposite direction from the token comparison.** This divergence
  is itself a finding: the CLI's own dollar-cost accounting and this
  benchmark's token-count proxy disagree about which condition is
  cheaper for the same 10 runs. Candidate explanation not yet
  investigated: `subagent_spawn` may incur additional non-token-metered
  overhead (e.g. thinking-token billing inside the spawned subagent, or a
  service-tier difference) that `usage.total_tokens` does not capture.
  This is logged as an open question, not resolved here -- a production
  decision must not pick whichever proxy happens to support the desired
  conclusion (constraint 5).
- Explanation candidate for the quality/margin result: single task, n=5,
  haiku/low tier -- underpowered by design (this run's purpose was to
  prove the tool's plumbing, not to answer the production question).

**Action:** re-run at the pinned production tier (sonnet/medium) across
all 3 tasks before any Phase 4/7 decision leans on this benchmark's
quality or cost axis. The token/cost divergence above should be
investigated as its own question before being treated as either result.

## Files

- `tasks/*.json` -- frozen task corpus + rubric (3 tasks).
- `fixtures/*.py` -- frozen synthetic fixtures, one per task.
- `lib/usage.py` -- pure: parse a `claude -p --output-format json` result
 into the raw usage fields this benchmark records; manipulation-check.
- `lib/provenance.py` -- build the reproducibility-manifest sidecar.
- `lib/prompts.py` -- build the two condition prompts from a task + the
 live `tools/skill-runner.sh` output (never a hand-copied procedure).
- `lib/stats.py` -- paired t-test + non-inferiority verdict, stdlib only
 (no scipy/numpy in this repo's dependency set), critical values sourced
 from the NIST/SEMATECH e-Handbook of Statistical Methods §1.3.6.7.
- `run_benchmark.py` -- the tool: N replications × 2 conditions,
 randomized order, resumable (writes `state.json` after every run so a
 killed process loses at most the in-flight run).
- `score_quality.py` -- blind LLM-judge scoring (2 evaluator configs).
- `analyze_results.py` -- ties raw + scored records together, reports the
 paired comparisons and the non-inferiority verdict.
- `tests/test_bench_agent_cost.py` (repo root `tests/`) -- unit tests for
 `lib/usage.py` and `lib/stats.py`, no live API calls.
