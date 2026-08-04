# Lessons

- Distinguish model-family independence from distinct-model validation.
  Sol, Terra, and Luna are one GPT-5.6 family, so only one is independent for a
  cross-family test; however, when the user requests all three, Terra and Luna
  remain required as separate model validations for within-family robustness.
  Never collapse those two experimental questions into one.

- A fresh workspace and mode-`0700` result directory do not prove blind reads
  when sequential model processes share the same OS user. Before the next rater,
  make all prior outputs mode `000` outside its writable roots or use a separate
  OS identity; then audit captured tool traces. Trace evidence of no access is
  corroboration, not a substitute for enforced non-readability.

- When a disagreement set mixes `none`/shape boundaries with shape/shape
  choices, report those strata separately. Exact A/B alignment can make a model
  look balanced because of `none` votes even while its shape decisions strongly
  favor one rater.
