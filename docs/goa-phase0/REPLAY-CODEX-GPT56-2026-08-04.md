# GOA Phase 0: Codex GPT-5.6 replay (2026-08-04)

## Scope

This replay evaluates three distinct Codex model IDs:

- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`

They are three models in the single GPT-5.6 family. The Sol pass supplies one
OpenAI-family comparison with the historical raters; the Terra and Luna passes
measure additional within-family, cross-model robustness. They are not counted
as three independent model families.

The frozen protocol, prompt, and rubric came from commit
`3829f543c7233130caab0742fe61598c5ff82c95`.

## Blind execution

Each model labelled the same six original lots (`60, 60, 58, 58, 58, 57`) for
351 cases total. Every lot used a fresh work directory and an ephemeral Codex
session with:

```text
model_reasoning_effort="xhigh"
project_doc_max_bytes=0
--sandbox workspace-write
--ephemeral
--skip-git-repo-check
```

Before every model pass, all 18 historical label, consensus, disagreement, and
adjudication JSONL files were moved into a mode-`000` quarantine. Completed lots
from the current pass were also mode `000` until the pass ended. The quarantine
was restored before scoring.

The later Codex processes ran under the same operating-system user as the
earlier ones. Earlier Codex outputs were outside each fresh workspace and were
never supplied to the model, but they were not protected by a separate UID or an
explicit OS read-denial rule. This means strict non-readability between the
three Codex passes was not technically guaranteed. A post-run audit of every
captured Codex stdout/stderr trace found:

- zero Terra references to Sol outputs, historical labels, scores, or archives;
- zero Luna references to Sol/Terra outputs, historical labels, scores, or
  archives;
- only the current lot workdir and the frozen `label-rubric.md` path referenced
  by either model.

The traces therefore corroborate that no cross-pass access occurred, while not
turning that observation into an OS-level isolation claim. A future replay
should make earlier model result directories mode `000` before starting the
next model, or use a separate OS identity.

An external validator rejected a lot unless it preserved the exact input order
and identifiers, contained no duplicates, used the frozen label/confidence
vocabularies, and matched the exact four-field output schema. All three passes
validated at 351 rows and 351 unique case IDs without repair or relabelling.

## Agreement with historical raters

The A/B baseline remains Cohen kappa `0.554`, with `287/351` raw agreement.

| Codex model | Routable | kappa vs A | Raw vs A | kappa vs B | Raw vs B | Fleiss A/B/model | Majority settled | Three-way split |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sol | 136 | 0.397 | 244/351 | 0.550 | 266/351 | 0.494 | 341 | 10 |
| Terra | 99 | 0.495 | 276/351 | 0.552 | 278/351 | 0.533 | 347 | 4 |
| Luna | 148 | 0.384 | 236/351 | 0.499 | 252/351 | 0.468 | 337 | 14 |

On the 64 cases where A and B disagree, counting `none` as an exact vote:

| Codex model | Matches A | Matches B | Matches neither |
|---|---:|---:|---:|
| Sol | 16 | 38 | 10 |
| Terra | 29 | 31 | 4 |
| Luna | 17 | 33 | 14 |

The shape-only comparison is the correct counterpart to the historical C-rater
observation:

| Rater | Matches A's shape | Matches B's shape |
|---|---:|---:|
| Historical C | 2 | 20 |
| Sol | 8 | 31 |
| Terra | 9 | 23 |
| Luna | 9 | 28 |

Of the 64 disagreements, 46 are `none`/shape boundary disagreements and only 18
compare two different shapes. On those 18 cases, the A/B/neither counts are
`6/9/3` for Sol, `5/9/4` for Terra, and `6/9/3` for Luna.

All three Codex models therefore align more often with B on shape decisions.
Terra appears nearly balanced only when its 20 agreements with A on `none` are
included. This weakens the hypothesis that the previous B/C shape alignment was
solely a shared-family effect, but the 18-case direct-shape subset is small,
agreement is not ground truth, and the result does not establish that B is
correct.

## Agreement between Codex models

| Pair | Cohen kappa | Raw agreement | Shape agreement among routable cases |
|---|---:|---:|---:|
| Sol / Terra | 0.641 | 282/351 | 76/145 (0.524) |
| Sol / Luna | 0.623 | 268/351 | 85/168 (0.506) |
| Terra / Luna | 0.591 | 269/351 | 75/157 (0.478) |

Fleiss kappa across Sol, Terra, and Luna is `0.617`. This is evidence of
meaningful within-family robustness, while the remaining disagreement shows
that the three model IDs are not interchangeable validators.

The raters also have materially different routing propensities: A routes 71
cases, B 93, Sol 136, Terra 99, and Luna 148. Kappa therefore combines a
`none`/shape boundary shift with disagreements between shapes.

## Provenance manifest

| Property | Recorded value |
|---|---|
| Codex CLI | `codex-cli 0.146.0` |
| Model IDs | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` |
| Reasoning effort | `xhigh` for every lot and model |
| Prompt SHA-256 | `8e588ffca4ed0df23b61820a63d272fb4383b2181fd395fc06f392dc5abc1eb7` |
| Rubric SHA-256 | `c5c3f252f29dc979ef87e145ab36627688c384109e7d048e8bde1b377b4c2da9` |
| Protocol SHA-256 | `ebda43dc5a9f7477ab1edd229630cb997c2a723bdf7b88b44ace1f32bb532a4f` |
| Generalized runner SHA-256 | `21ce8005e1cb601a6de92758fc19422a261f8225468f0a9bdef79d31d8dbc598` |
| Validator SHA-256 | `da209bf52f380a3d75e83db649ccc2927d4599e31a6f9f4b45b5c0a1ae8b7155` |

The CLI exposes the model IDs but not a backend checkpoint/build identifier, so
the latter is unknown rather than inferred. Sol ran through the pre-generalized
runner with the same core command and validator; the recorded generalized
runner hash exactly covers the Terra and Luna invocations and the later cleanup
change.

## Artifacts

Canonical private directory:

```text
~/.claude/goa-phase0/replays/2026-08-04-codex-gpt56/
```

Aggregate SHA-256 values are computed by hashing the six ordered per-lot file
hashes for each model:

| Model | Aggregate SHA-256 |
|---|---|
| Sol | `e4f185956bb743e9f2fb37f15c1a093d13a4e487a0173b83ec7eba01f37a57ce` |
| Terra | `73474f8bf988292ca8eb7060c80e53ed9ef534a2b248d49d40d81401c9a1706b` |
| Luna | `02debe9cb5e82182a430ce6c46276720423ffe08661ddb18eabef663622fca41` |

## Decision boundary

The new model votes are validation evidence, not automatic adjudication. They
must not silently replace the planned human review of unresolved cases or be
folded with A/B/C into a generic five- or six-rater majority. PR #92 remains
blocked on the explicit human-arbitration step defined in the Phase 0 protocol.

No acceptance threshold or confidence interval was pre-registered for this
replay, so the agreement values are descriptive rather than a pass/fail result.
The confidence field is also not used by the scorer and is heavily concentrated
on `high` (Sol 296, Terra 279, Luna 261). Finally, each model's six lot sessions
were merged as one rater; this run does not estimate within-model replay
variance.
