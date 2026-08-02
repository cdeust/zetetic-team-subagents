# Laplace: update belief explicitly

Use this reference when evidence should change a degree of belief and the prior,
likelihood or sensitivity of that change needs to be visible.

## Core relation

For hypothesis `H` and evidence `E`:

`P(H | E) = P(E | H) P(H) / P(E)`

The equation does not choose the hypotheses, prior or likelihood model. Those
are substantive decisions that require evidence and sensitivity analysis.

## Procedure

1. Enumerate the material hypotheses, including a meaningful alternative.
2. Elicit or estimate priors from stated evidence. If no prior is defensible,
   use a range and label it as a sensitivity input.
3. Model how likely the evidence would be under each hypothesis. Account for
   dependence rather than multiplying correlated observations as if separate.
4. Update and show the calculation or reproducible code.
5. Vary priors and likelihood assumptions across defensible ranges.
6. Check calibration against held-out or historical cases when such cases
   exist.
7. Report the posterior together with model uncertainty and decision costs.

## Output

- Hypothesis set
- Prior provenance or sensitivity range
- Likelihood evidence and dependency assumptions
- Update calculation
- Sensitivity analysis
- Posterior interpretation, uncertainty and decision implications

## Cautions

- A posterior can be precise while the model is wrong.
- Reusing the same evidence in the prior and likelihood double-counts it.
- A narrow hypothesis set can force misleading certainty.
- Refuse a numeric posterior when the inputs would have to be invented.

## Primary and methodological sources

- Bayes, T. (1763). “An Essay towards Solving a Problem in the Doctrine of
  Chances.” *Philosophical Transactions of the Royal Society of London*.
- Laplace, P.-S. (1814). *Essai philosophique sur les probabilités*.
- Laplace, P.-S. (1812). *Théorie analytique des probabilités*.
- Jaynes, E. T. (2003). *Probability Theory: The Logic of Science*. Cambridge
  University Press.
